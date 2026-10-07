from decimal import Decimal

from sqlalchemy import text

from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.valores import ValorInvalido


def calcular_quitacoes(itens, pagamentos):
    """Associa cada despesa integralmente coberta ao pagamento que completou sua quitação."""
    pagamentos_ordenados = sorted(
        pagamentos,
        key=lambda item: (item["data_pagamento"], item["id"]),
    )
    faixas = []
    total_pago = Decimal("0")
    for pagamento in pagamentos_ordenados:
        total_pago += Decimal(str(pagamento["valor"]))
        faixas.append((total_pago, pagamento))

    resultado = {}
    acumulado = Decimal("0")
    for item in sorted(itens, key=lambda linha: linha["id"]):
        acumulado += Decimal(str(item["valor"]))
        pagamento_quitador = next(
            (pagamento for limite, pagamento in faixas if limite >= acumulado),
            None,
        )
        resultado[item["id"]] = pagamento_quitador
    return resultado


def registrar_movimento_pagamento_om(conn, om, pagamento, usuario_id):
    categoria_id = conn.execute(text("""
        SELECT id FROM financeiro3_categorias
        WHERE codigo='A_CLASSIFICAR' AND natureza='DESPESA'
    """)).scalar()
    if not categoria_id:
        raise ValorInvalido("A categoria A_CLASSIFICAR não está configurada.")

    rotulo = "Adiantamento" if pagamento["tipo"] == "ADIANTAMENTO" else "Quitação"
    movimento = conn.execute(text("""
        INSERT INTO financeiro3_om_movimentos
          (om_id,pagamento_id,data_movimento,centro_custo_id,categoria_id,
           descricao,valor,criado_por)
        VALUES (:om,:pagamento,:data,:centro,:categoria,:descricao,:valor,:usuario)
        ON CONFLICT (pagamento_id) DO UPDATE SET
          data_movimento=EXCLUDED.data_movimento,
          descricao=EXCLUDED.descricao,
          valor=EXCLUDED.valor
        RETURNING *
    """), {
        "om": om["id"],
        "pagamento": pagamento["id"],
        "data": pagamento["data_pagamento"],
        "centro": om["centro_custo_id"],
        "categoria": categoria_id,
        "descricao": f"{rotulo} da OM {om['numero_om']}",
        "valor": -Decimal(str(pagamento["valor"])),
        "usuario": usuario_id,
    }).mappings().one()
    registrar_evento(
        conn,
        entidade="OM_MOVIMENTO",
        entidade_id=movimento["id"],
        evento="REGISTRADO",
        dados_novos=dict(movimento),
    )
    return movimento


def reconciliar_quitacao_om(conn, om_id):
    """Recalcula a quitação das linhas e reflete o resultado nas contas vinculadas."""
    om = conn.execute(text("""
        SELECT id,numero_om FROM financeiro3_oms
        WHERE id=:id AND removido_em IS NULL
    """), {"id": om_id}).mappings().first()
    if not om:
        return []

    itens = [dict(item) for item in conn.execute(text("""
        SELECT * FROM financeiro3_om_itens
        WHERE om_id=:om AND status='ATIVO'
        ORDER BY id FOR UPDATE
    """), {"om": om_id}).mappings().all()]
    pagamentos = [dict(item) for item in conn.execute(text("""
        SELECT * FROM financeiro3_om_pagamentos
        WHERE om_id=:om AND status='PAGO'
        ORDER BY data_pagamento,id
    """), {"om": om_id}).mappings().all()]
    quitacoes = calcular_quitacoes(itens, pagamentos)

    for item in itens:
        pagamento = quitacoes[item["id"]]
        quitada = pagamento is not None
        estado_mudou = (
            bool(item.get("quitada")) != quitada
            or item.get("quitada_pagamento_id") != (pagamento["id"] if pagamento else None)
        )
        if not estado_mudou:
            continue
        novo = conn.execute(text("""
            UPDATE financeiro3_om_itens
            SET quitada=:quitada,
                quitada_pagamento_id=:pagamento,
                data_quitacao=:data,
                quitada_por=:usuario
            WHERE id=:id RETURNING *
        """), {
            "quitada": quitada,
            "pagamento": pagamento["id"] if pagamento else None,
            "data": pagamento["data_pagamento"] if pagamento else None,
            "usuario": pagamento.get("pago_por") if pagamento else None,
            "id": item["id"],
        }).mappings().one()
        registrar_evento(
            conn,
            entidade="OM_ITEM",
            entidade_id=item["id"],
            evento="QUITADA" if quitada else "QUITACAO_REVERTIDA",
            dados_anteriores=item,
            dados_novos=dict(novo),
        )

    contas = [dict(conta) for conta in conn.execute(text("""
        SELECT c.*,i.status AS item_status,i.quitada,i.quitada_pagamento_id,
          i.data_quitacao,i.quitada_por
        FROM financeiro3_pagamento_contas c
        JOIN financeiro3_om_itens i ON i.id=c.om_item_id
        WHERE c.om_id=:om AND c.excluida_em IS NULL
        ORDER BY c.id FOR UPDATE
    """), {"om": om_id}).mappings().all()]
    contas_atualizadas = []
    for conta in contas:
        if conta["item_status"] == "ATIVO" and conta["quitada"]:
            precisa_atualizar = (
                conta["status_reembolso"] != "REEMBOLSADA"
                or conta.get("reembolso_om_pagamento_id") != conta["quitada_pagamento_id"]
                or conta.get("numero_om") != om["numero_om"]
            )
            if not precisa_atualizar:
                continue
            novo = conn.execute(text("""
                UPDATE financeiro3_pagamento_contas
                SET status_reembolso='REEMBOLSADA',numero_om=:numero,
                    data_reembolso=:data,reembolso_por=:usuario,
                    reembolso_om_pagamento_id=:pagamento,
                    status_sincronizacao='PENDENTE',atualizado_em=NOW()
                WHERE id=:id RETURNING *
            """), {
                "numero": om["numero_om"],
                "data": conta["data_quitacao"],
                "usuario": conta["quitada_por"],
                "pagamento": conta["quitada_pagamento_id"],
                "id": conta["id"],
            }).mappings().one()
            evento = "REEMBOLSO_AUTOMATICO_OM"
        elif conta.get("reembolso_om_pagamento_id"):
            novo = conn.execute(text("""
                UPDATE financeiro3_pagamento_contas
                SET status_reembolso='PENDENTE',numero_om=NULL,data_reembolso=NULL,
                    reembolso_por=NULL,reembolso_om_pagamento_id=NULL,
                    status_sincronizacao='PENDENTE',atualizado_em=NOW()
                WHERE id=:id RETURNING *
            """), {"id": conta["id"]}).mappings().one()
            evento = "REEMBOLSO_AUTOMATICO_OM_REVERTIDO"
        else:
            continue
        registrar_evento(
            conn,
            entidade="PERFIL_PAGAMENTO_CONTA",
            entidade_id=conta["id"],
            evento=evento,
            dados_anteriores=conta,
            dados_novos=dict(novo),
        )
        contas_atualizadas.append(conta["id"])
    return contas_atualizadas
