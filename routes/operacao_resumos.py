from collections import defaultdict
from datetime import date, timedelta
from math import ceil
import unicodedata

from sqlalchemy import text

from routes.operacao_producao import CATEGORIAS_IMPACTO


DIAS_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


def _float(valor):
    return float(valor or 0)


def _normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(char for char in texto if not unicodedata.combining(char)).lower()


def _ids_validos(valores, permitidos):
    permitidos = {int(valor) for valor in permitidos}
    resultado = []
    for valor in valores or []:
        try:
            numero = int(valor)
        except (TypeError, ValueError):
            continue
        if numero in permitidos and numero not in resultado:
            resultado.append(numero)
    return resultado


def _clausula_in(prefixo, valores, params):
    nomes = []
    for indice, valor in enumerate(valores):
        nome = f"{prefixo}_{indice}"
        nomes.append(f":{nome}")
        params[nome] = valor
    return ", ".join(nomes)


def classificar_atividade(nome):
    normalizado = _normalizar(nome)
    if "renov" in normalizado:
        return "producao"
    if "corretiv" in normalizado:
        return "corretiva"
    if "preventiv" in normalizado:
        return "preventiva"
    return "outras"


def calcular_indicadores_maquina(total_minutos, corretiva_minutos, preventiva_minutos, producao_minutos):
    total = max(0.0, _float(total_minutos))
    corretiva = max(0.0, _float(corretiva_minutos))
    preventiva = max(0.0, _float(preventiva_minutos))
    producao = max(0.0, _float(producao_minutos))
    indisponivel = min(total, corretiva + preventiva)
    disponivel = max(0.0, total - indisponivel)
    return {
        "disponibilidade": (disponivel / total * 100.0) if total else 0.0,
        "utilizacao": (producao / disponivel * 100.0) if disponivel else 0.0,
        "horas_total": total / 60.0,
        "horas_corretiva": corretiva / 60.0,
        "horas_preventiva": preventiva / 60.0,
        "horas_producao": producao / 60.0,
    }


def _listas(conn):
    ehs = conn.execute(
        text("SELECT id, eh AS nome FROM entre_house ORDER BY eh")
    ).mappings().all()
    frentes = conn.execute(
        text(
            """
            SELECT id, frente AS nome, codigo
            FROM frente_equipe
            WHERE COALESCE(escopo, 'EH') = 'EH'
            ORDER BY COALESCE(ordem, 999), frente
            """
        )
    ).mappings().all()
    maquinas = conn.execute(
        text(
            """
            SELECT id, tag, descricao
            FROM maquina
            WHERE ativo = TRUE
            ORDER BY tag
            """
        )
    ).mappings().all()
    return ehs, frentes, maquinas


def _producao(conn, eh_ids, frente_ids):
    params = {}
    ehs_sql = _clausula_in("eh", eh_ids, params)
    frentes_sql = _clausula_in("frente", frente_ids, params)
    return conn.execute(
        text(
            f"""
            WITH base AS (
                SELECT p.eh_id, p.frente_id, p.data::date AS data,
                       SUM(p.planejado)::float AS planejado, 0.0::float AS realizado
                FROM producao_planejada p
                WHERE p.eh_id IN ({ehs_sql}) AND p.frente_id IN ({frentes_sql})
                GROUP BY p.eh_id, p.frente_id, p.data
                UNION ALL
                SELECT r.eh_id, r.frente_id, r.data::date AS data,
                       0.0::float AS planejado, SUM(r.realizado)::float AS realizado
                FROM producao_realizada r
                WHERE r.eh_id IN ({ehs_sql}) AND r.frente_id IN ({frentes_sql})
                GROUP BY r.eh_id, r.frente_id, r.data
            )
            SELECT b.eh_id, e.eh AS eh, b.frente_id, f.frente, f.codigo, b.data,
                   SUM(b.planejado)::float AS planejado,
                   SUM(b.realizado)::float AS realizado
            FROM base b
            JOIN entre_house e ON e.id = b.eh_id
            JOIN frente_equipe f ON f.id = b.frente_id
            GROUP BY b.eh_id, e.eh, b.frente_id, f.frente, f.codigo, b.data
            ORDER BY b.data, e.eh, f.frente
            """
        ),
        params,
    ).mappings().all()


def _resumir_producao(rows, finalizada_ids):
    finalizadas = {int(valor) for valor in finalizada_ids}
    diario = defaultdict(lambda: {"planejado": 0.0, "realizado": 0.0})
    planos = {}
    frentes = {}
    renovacao_diaria = defaultdict(float)
    datas_realizadas = set()

    for row in rows:
        data_iso = row["data"].isoformat()
        planejado = _float(row["planejado"])
        realizado = _float(row["realizado"])
        diario[data_iso]["planejado"] += planejado
        diario[data_iso]["realizado"] += realizado
        if realizado > 0:
            datas_realizadas.add(data_iso)

        plano = planos.setdefault(
            int(row["eh_id"]),
            {
                "id": int(row["eh_id"]),
                "nome": row["eh"],
                "finalizado": int(row["eh_id"]) in finalizadas,
                "planejado": 0.0,
                "realizado": 0.0,
                "dias_realizados": set(),
                "datas_planejadas": set(),
                "ultima_data": None,
                "ultima_data_realizada": None,
            },
        )
        plano["planejado"] += planejado
        plano["realizado"] += realizado
        plano["ultima_data"] = max(plano["ultima_data"] or row["data"], row["data"])
        if planejado > 0:
            plano["datas_planejadas"].add(row["data"])
        if realizado > 0:
            plano["dias_realizados"].add(row["data"])
            plano["ultima_data_realizada"] = max(plano["ultima_data_realizada"] or row["data"], row["data"])
        if _normalizar(row["codigo"]) == "renovacao" or "renov" in _normalizar(row["frente"]):
            renovacao_diaria[data_iso] += realizado

        frente = frentes.setdefault(
            int(row["frente_id"]),
            {"id": int(row["frente_id"]), "nome": row["frente"], "codigo": row["codigo"], "planejado": 0.0, "realizado": 0.0},
        )
        frente["planejado"] += planejado
        frente["realizado"] += realizado

    acumulado_planejado = 0.0
    acumulado_realizado = 0.0
    serie = []
    for data_iso in sorted(diario):
        item = diario[data_iso]
        acumulado_planejado += item["planejado"]
        acumulado_realizado += item["realizado"]
        serie.append(
            {
                "data": data_iso,
                **item,
                "planejado_acumulado": acumulado_planejado,
                "realizado_acumulado": acumulado_realizado,
                "diferenca": acumulado_realizado - acumulado_planejado,
            }
        )

    hoje = date.today()
    for plano in planos.values():
        plano["diferenca"] = plano["realizado"] - plano["planejado"]
        plano["aderencia"] = (plano["realizado"] / plano["planejado"] * 100.0) if plano["planejado"] else 0.0
        plano["media_dia"] = plano["realizado"] / len(plano["dias_realizados"]) if plano["dias_realizados"] else 0.0
        plano["restante"] = max(0.0, plano["planejado"] - plano["realizado"])
        plano["dias_estimados"] = None
        plano["data_projetada"] = None
        plano["ritmo_necessario"] = None
        if not plano["finalizado"] and plano["restante"] > 0:
            if plano["media_dia"] > 0:
                plano["dias_estimados"] = ceil(plano["restante"] / plano["media_dia"])
                base = max(hoje, plano["ultima_data_realizada"] or hoje)
                plano["data_projetada"] = base + timedelta(days=plano["dias_estimados"])
            referencia = max(hoje, plano["ultima_data_realizada"] or hoje)
            dias_futuros = len([d for d in plano["datas_planejadas"] if d > referencia])
            if dias_futuros:
                plano["ritmo_necessario"] = plano["restante"] / dias_futuros
        plano["dias_realizados"] = len(plano["dias_realizados"])
        plano["datas_planejadas"] = len(plano["datas_planejadas"])

    for frente in frentes.values():
        frente["diferenca"] = frente["realizado"] - frente["planejado"]
        frente["aderencia"] = (frente["realizado"] / frente["planejado"] * 100.0) if frente["planejado"] else 0.0

    total_planejado = sum(item["planejado"] for item in diario.values())
    total_realizado = sum(item["realizado"] for item in diario.values())
    quantidade_dias = 0
    if serie:
        inicio = date.fromisoformat(serie[0]["data"])
        fim = date.fromisoformat(serie[-1]["data"])
        quantidade_dias = (fim - inicio).days + 1
    else:
        inicio = fim = None

    return {
        "serie": serie,
        "planos": sorted(planos.values(), key=lambda item: item["nome"]),
        "frentes": sorted(frentes.values(), key=lambda item: item["nome"]),
        "inicio": inicio,
        "fim": fim,
        "renovacao_por_data": dict(renovacao_diaria),
        "kpis": {
            "planejado": total_planejado,
            "realizado": total_realizado,
            "diferenca": total_realizado - total_planejado,
            "aderencia": (total_realizado / total_planejado * 100.0) if total_planejado else 0.0,
            "media_dia_produzido": total_realizado / len(datas_realizadas) if datas_realizadas else 0.0,
            "media_dia_periodo": total_realizado / quantidade_dias if quantidade_dias else 0.0,
            "dias_com_producao": len(datas_realizadas),
            "dias_periodo": quantidade_dias,
        },
    }


def _montar_tabela_diaria(rows, impactos, observacoes_registradas=None):
    """Monta uma linha por EH e dia, mantendo acumulados independentes por plano."""
    por_plano = {}
    for row in rows:
        plano = por_plano.setdefault(
            int(row["eh_id"]),
            {"nome": row["eh"], "dias": defaultdict(lambda: {"planejado": 0.0, "realizado": 0.0})},
        )
        dia = plano["dias"][row["data"]]
        dia["planejado"] += _float(row["planejado"])
        dia["realizado"] += _float(row["realizado"])

    anotacoes = defaultdict(list)
    for impacto in impactos:
        anotacoes[(int(impacto["eh_id"]), impacto["data"])].append(
            f'Impacto — {impacto["frente"]}: {impacto["descricao"]} ({int(impacto["minutos_perdidos"] or 0)} min)'
        )
    for observacao in observacoes_registradas or []:
        anotacoes[(int(observacao["eh_id"]), observacao["data"])].append(
            observacao["observacao"]
        )

    tabela = []
    for eh_id, plano in sorted(por_plano.items(), key=lambda item: item[1]["nome"]):
        if not plano["dias"]:
            continue
        inicio = min(plano["dias"])
        fim = max(plano["dias"])
        dias_planejados = [item["planejado"] for item in plano["dias"].values() if item["planejado"] > 0]
        media_planejada = sum(dias_planejados) / len(dias_planejados) if dias_planejados else 0.0
        acumulado_planejado = 0.0
        acumulado_realizado = 0.0
        data_atual = inicio
        while data_atual <= fim:
            valores = plano["dias"].get(data_atual, {"planejado": 0.0, "realizado": 0.0})
            acumulado_planejado += valores["planejado"]
            acumulado_realizado += valores["realizado"]
            diferenca = acumulado_realizado - acumulado_planejado
            textos = anotacoes.get((eh_id, data_atual), [])
            tabela.append(
                {
                    "data": data_atual,
                    "dia_semana": DIAS_SEMANA[data_atual.weekday()],
                    "local": plano["nome"],
                    "planejado_dia": valores["planejado"],
                    "planejado_total": acumulado_planejado,
                    "realizado_dia": valores["realizado"],
                    "realizado_total": acumulado_realizado,
                    "diferenca": diferenca,
                    "atraso_dias": diferenca / media_planejada if media_planejada else None,
                    "observacoes": textos[0] if textos else "",
                    "complementos": textos[1:],
                }
            )
            data_atual += timedelta(days=1)
    return tabela


def _impactos(conn, eh_ids, frente_ids, inicio, fim):
    if not inicio or not fim:
        return []
    params = {"inicio": inicio, "fim": fim}
    ehs_sql = _clausula_in("impacto_eh", eh_ids, params)
    frentes_sql = _clausula_in("impacto_frente", frente_ids, params)
    return conn.execute(
        text(
            f"""
            SELECT i.id, i.data, i.eh_id, i.frente_id, i.minutos_perdidos, i.categoria, i.descricao,
                   i.responsavel, i.providencia, i.status, e.eh, f.frente
            FROM operacao_impacto i
            JOIN entre_house e ON e.id = i.eh_id
            JOIN frente_equipe f ON f.id = i.frente_id
            WHERE i.eh_id IN ({ehs_sql})
              AND i.frente_id IN ({frentes_sql})
              AND i.data BETWEEN :inicio AND :fim
            ORDER BY i.data DESC, i.minutos_perdidos DESC, i.id DESC
            """
        ),
        params,
    ).mappings().all()


def _observacoes(conn, eh_ids, frente_ids, inicio, fim):
    if not inicio or not fim:
        return []
    params = {"inicio": inicio, "fim": fim}
    ehs_sql = _clausula_in("observacao_eh", eh_ids, params)
    frentes_sql = _clausula_in("observacao_frente", frente_ids, params)
    return conn.execute(
        text(
            f"""
            SELECT o.id, o.data, o.eh_id, o.frente_id, o.observacao,
                   e.eh, f.frente
            FROM operacao_observacao o
            JOIN entre_house e ON e.id = o.eh_id
            JOIN frente_equipe f ON f.id = o.frente_id
            WHERE o.eh_id IN ({ehs_sql})
              AND o.frente_id IN ({frentes_sql})
              AND o.data BETWEEN :inicio AND :fim
            ORDER BY o.data, o.id
            """
        ),
        params,
    ).mappings().all()


def _parte_diaria(conn, maquina_ids, inicio, fim, renovacao_por_data):
    if not maquina_ids or not inicio or not fim:
        return {"maquinas": [], "eventos": [], "atividades": [], "serie": [], "grafico": {}}
    params = {"inicio": inicio, "fim": fim}
    maquinas_sql = _clausula_in("maquina", maquina_ids, params)
    rows = conn.execute(
        text(
            f"""
            SELECT pd.id, pd.data, pd.maquina_id, m.tag, m.descricao AS maquina_descricao,
                   a.nome AS atividade, pd.obs,
                   to_char(pd.hora_inicio, 'HH24:MI') AS hora_inicio,
                   to_char(pd.hora_fim, 'HH24:MI') AS hora_fim,
                   EXTRACT(EPOCH FROM (
                       CASE WHEN pd.hora_fim >= pd.hora_inicio
                           THEN pd.hora_fim - pd.hora_inicio
                           ELSE pd.hora_fim - pd.hora_inicio + INTERVAL '24 hours'
                       END
                   )) / 60.0 AS duracao_minutos
            FROM parte_diaria pd
            JOIN maquina m ON m.id = pd.maquina_id
            JOIN atividade a ON a.id = pd.atividade_id
            WHERE pd.maquina_id IN ({maquinas_sql})
              AND pd.data BETWEEN :inicio AND :fim
            ORDER BY pd.data, m.tag, pd.hora_inicio, pd.id
            """
        ),
        params,
    ).mappings().all()

    maquinas = {}
    atividades = defaultdict(lambda: {"minutos": 0.0, "ocorrencias": 0})
    serie = defaultdict(lambda: {"total": 0.0, "producao": 0.0, "corretiva": 0.0, "preventiva": 0.0})
    eventos = []
    for row in rows:
        minutos = _float(row["duracao_minutos"])
        classe = classificar_atividade(row["atividade"])
        maquina = maquinas.setdefault(
            int(row["maquina_id"]),
            {
                "id": int(row["maquina_id"]),
                "tag": row["tag"],
                "descricao": row["maquina_descricao"],
                "total_minutos": 0.0,
                "corretiva_minutos": 0.0,
                "preventiva_minutos": 0.0,
                "producao_minutos": 0.0,
                "dias": set(),
            },
        )
        maquina["total_minutos"] += minutos
        maquina[f"{classe}_minutos"] = maquina.get(f"{classe}_minutos", 0.0) + minutos
        maquina["dias"].add(row["data"])
        chave_atividade = (row["tag"], row["atividade"])
        atividades[chave_atividade]["minutos"] += minutos
        atividades[chave_atividade]["ocorrencias"] += 1
        data_iso = row["data"].isoformat()
        serie[(int(row["maquina_id"]), data_iso)]["total"] += minutos
        if classe in serie[(int(row["maquina_id"]), data_iso)]:
            serie[(int(row["maquina_id"]), data_iso)][classe] += minutos
        eventos.append({**dict(row), "classe": classe, "duracao_minutos": minutos})

    resultado_maquinas = []
    for maquina in maquinas.values():
        indicadores = calcular_indicadores_maquina(
            maquina["total_minutos"], maquina["corretiva_minutos"], maquina["preventiva_minutos"], maquina["producao_minutos"]
        )
        horas_producao = indicadores["horas_producao"]
        producao_total = sum(renovacao_por_data.get(data.isoformat(), 0.0) for data in maquina["dias"])
        velocidades = []
        for data_maquina in maquina["dias"]:
            item_dia = serie[(maquina["id"], data_maquina.isoformat())]
            horas_dia = item_dia["producao"] / 60.0
            if horas_dia > 0:
                velocidades.append(renovacao_por_data.get(data_maquina.isoformat(), 0.0) / horas_dia)
        resultado_maquinas.append(
            {
                **maquina,
                **indicadores,
                "dias": len(maquina["dias"]),
                "media_horas_dia": indicadores["horas_total"] / len(maquina["dias"]) if maquina["dias"] else 0.0,
                "media_producao_dia": indicadores["horas_producao"] / len(maquina["dias"]) if maquina["dias"] else 0.0,
                "media_corretiva_dia": indicadores["horas_corretiva"] / len(maquina["dias"]) if maquina["dias"] else 0.0,
                "media_preventiva_dia": indicadores["horas_preventiva"] / len(maquina["dias"]) if maquina["dias"] else 0.0,
                "velocidade_consolidada": producao_total / horas_producao if horas_producao else 0.0,
                "velocidade_media_diaria": sum(velocidades) / len(velocidades) if velocidades else 0.0,
            }
        )

    atividades_resultado = [
        {"maquina": chave[0], "atividade": chave[1], **valor, "horas": valor["minutos"] / 60.0}
        for chave, valor in atividades.items()
    ]
    atividades_resultado.sort(key=lambda item: item["minutos"], reverse=True)
    serie_resultado = []
    for (maquina_id, data_iso), valores in sorted(serie.items(), key=lambda item: (item[0][1], item[0][0])):
        maquina = maquinas[maquina_id]
        horas_producao = valores["producao"] / 60.0
        serie_resultado.append(
            {
                "data": data_iso,
                "maquina": maquina["tag"],
                **valores,
                "outras": max(0.0, valores["total"] - valores["producao"] - valores["corretiva"] - valores["preventiva"]),
                "velocidade": renovacao_por_data.get(data_iso, 0.0) / horas_producao if horas_producao else 0.0,
            }
        )
    return {
        "maquinas": resultado_maquinas,
        "eventos": eventos,
        "atividades": atividades_resultado,
        "serie": serie_resultado,
        "grafico": {
            "labels": [f'{item["data"]} · {item["maquina"]}' for item in serie_resultado],
            "producao": [round(item["producao"] / 60.0, 2) for item in serie_resultado],
            "corretiva": [round(item["corretiva"] / 60.0, 2) for item in serie_resultado],
            "preventiva": [round(item["preventiva"] / 60.0, 2) for item in serie_resultado],
            "outras": [round(item["outras"] / 60.0, 2) for item in serie_resultado],
            "velocidade": [round(item["velocidade"], 2) for item in serie_resultado],
        },
    }


def carregar_resumo(conn, eh_ids=None, frente_ids=None, maquina_ids=None, incluir_parte_diaria=False, finalizada_ids=None, gerar=False):
    ehs, frentes, maquinas = _listas(conn)
    eh_ids = _ids_validos(eh_ids, [item["id"] for item in ehs])
    frente_ids = _ids_validos(frente_ids, [item["id"] for item in frentes])
    maquina_ids = _ids_validos(maquina_ids, [item["id"] for item in maquinas])
    finalizada_ids = _ids_validos(finalizada_ids, eh_ids)

    if not eh_ids and ehs:
        eh_ids = [int(ehs[0]["id"])]
    if not frente_ids:
        renovacao = next((item for item in frentes if _normalizar(item["codigo"]) == "renovacao" or "renov" in _normalizar(item["nome"])), None)
        if renovacao:
            frente_ids = [int(renovacao["id"])]
    if incluir_parte_diaria and not maquina_ids:
        p190 = next((item for item in maquinas if item["tag"] == "P190-66001"), None)
        if p190:
            maquina_ids = [int(p190["id"])]

    resultado = {
        "ehs": ehs,
        "frentes_disponiveis": frentes,
        "maquinas_disponiveis": maquinas,
        "eh_ids": eh_ids,
        "frente_ids": frente_ids,
        "maquina_ids": maquina_ids,
        "finalizada_ids": finalizada_ids,
        "incluir_parte_diaria": incluir_parte_diaria,
        "gerado": gerar,
        "erro": None,
    }
    if not gerar:
        return resultado
    if not eh_ids or not frente_ids:
        resultado["erro"] = "Selecione ao menos uma EH e uma frente para gerar o resumo."
        return resultado

    producao_rows = _producao(conn, eh_ids, frente_ids)
    producao = _resumir_producao(producao_rows, finalizada_ids)
    impactos = _impactos(conn, eh_ids, frente_ids, producao["inicio"], producao["fim"])
    observacoes = _observacoes(conn, eh_ids, frente_ids, producao["inicio"], producao["fim"])
    producao["tabela"] = _montar_tabela_diaria(producao_rows, impactos, observacoes)
    parte_diaria = _parte_diaria(
        conn, maquina_ids if incluir_parte_diaria else [], producao["inicio"], producao["fim"], producao["renovacao_por_data"]
    )
    impacto_por_categoria = defaultdict(float)
    for impacto in impactos:
        impacto_por_categoria[impacto["categoria"]] += _float(impacto["minutos_perdidos"])

    resultado.update(
        {
            "producao": producao,
            "impactos": impactos,
            "observacoes": observacoes,
            "impacto_horas": sum(_float(item["minutos_perdidos"]) for item in impactos) / 60.0,
            "impacto_grafico": {
                "labels": [dict(CATEGORIAS_IMPACTO).get(codigo, codigo) for codigo in impacto_por_categoria],
                "valores": [round(minutos / 60.0, 2) for minutos in impacto_por_categoria.values()],
            },
            "categorias_impacto": dict(CATEGORIAS_IMPACTO),
            "parte_diaria": parte_diaria,
            "grafico": {
                "labels": [item["data"] for item in producao["serie"]],
                "planejado": [item["planejado"] for item in producao["serie"]],
                "realizado": [item["realizado"] for item in producao["serie"]],
                "planejado_acumulado": [item["planejado_acumulado"] for item in producao["serie"]],
                "realizado_acumulado": [item["realizado_acumulado"] for item in producao["serie"]],
                "frente_labels": [item["nome"] for item in producao["frentes"]],
                "frente_planejado": [item["planejado"] for item in producao["frentes"]],
                "frente_realizado": [item["realizado"] for item in producao["frentes"]],
                "frente_backlog": [max(0.0, item["planejado"] - item["realizado"]) for item in producao["frentes"]],
            },
        }
    )
    return resultado
