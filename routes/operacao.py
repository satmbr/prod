# routes/operacao.py

from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine
from datetime import date, datetime

# Tenta importar do utils "real" se existir,
# senão cria versões de fallback para não travar o sistema.
try:
    from utils import nivel_requerido
except ImportError:
    def nivel_requerido(*roles):
        """Decorador de fallback: NÃO faz controle de acesso, só deixa a rota rodar."""
        def decorator(fn):
            return fn
        return decorator

try:
    from utils.calcular_duracao import calcular_duracao
except ImportError:
    def calcular_duracao(hora_inicio: str, hora_fim: str) -> int:
        """
        Fallback local para calcular duração em minutos a partir de strings 'HH:MM'.
        """
        fmt = "%H:%M"
        ini = datetime.strptime(str(hora_inicio), fmt)
        fim = datetime.strptime(str(hora_fim), fmt)
        delta = fim - ini
        return int(delta.total_seconds() // 60)

# Blueprint principal de Operação.
# O prefixo '/operacao' normalmente é aplicado no app.py ao registrar o blueprint.
bp = Blueprint("operacao", __name__)


@bp.route("/producao", methods=["GET"])
@nivel_requerido("admin", "gerente", "tecnico", "planejador", "visualizador")
def producao():
    """Visão de produção (renovação, parte diária, frentes e gauges).

    Esta função é uma adaptação da lógica antiga (psycopg2) para a nova
    estrutura com SQLAlchemy + get_engine(), mantendo os mesmos cálculos
    e o mesmo formato de dados esperado pelo template
    templates/operacao/producao.html.
    """
    engine = get_engine()

    # Filtros vindos da URL
    eh_id = request.args.get("eh_id")
    data_partdiaria = request.args.get("data_partdiaria")

    # Estruturas padrão para o template
    ehs = []
    dados = []                      # tabela de renovação (frente 01)
    dados_partdiaria = []           # tabela da parte diária P190-66001
    grafico_atividades = {"labels": [], "tempos": []}
    dados_carregamento = []         # tabela auxiliar de carregamento
    grafico_barra_carregamento = [] # gráfico barras/linhas frente 02
    grafico_bateria_carregamento = {}
    dados_resumo_frentes = []       # tabela consolidada de frentes
    percentuais_graficos = {}       # dados dos gauges

    with engine.connect() as conn:
        # ------------------------
        # Lista de EHs para o filtro
        # ------------------------
        ehs = conn.execute(
            text("SELECT id, nome FROM prumat_eh ORDER BY nome")
        ).mappings().all()

        if eh_id:
            # ================================================
            # BLOCO 1 — Preparação de dados por frente / data
            # ================================================
            frentes_interessadas = [
                "01 - Renovação",
                "02 - Carregamento_novo",
                "03 - Remoção_grampos",
                "04 - Remoção_galochas",
                "05 - Descarregamento_velho",
                "06 - Aplicação_grampos",
                "07 - Segregação_bons",
                "08 - Segregação_ruins",
                "09 - Descarregamento_novo",
            ]

            # Mapeia nomes de frentes para chaves numéricas internas
            frentes_map = {
                nome: idx + 1 for idx, nome in enumerate(frentes_interessadas)
            }

            # Busca toda a produção dessa EH (todas as frentes) e filtra em memória
            registros_frentes = conn.execute(
                text(
                    """
                    SELECT f.nome AS frente, p.data, p.executado
                    FROM prumat_producao p
                    JOIN prumat_frente_producao f ON p.frente_id = f.id
                    WHERE p.eh_id = :eh_id
                    ORDER BY p.data
                    """
                ),
                {"eh_id": eh_id},
            ).mappings().all()

            por_data = defaultdict(lambda: {k: 0 for k in frentes_map.values()})
            acumulados = {k: 0 for k in frentes_map.values()}
            datas_presentes = set()

            for row in registros_frentes:
                frente = row["frente"]
                data_row = row["data"]
                valor = row["executado"] or 0

                if frente not in frentes_map:
                    continue

                chave = frentes_map[frente]
                por_data[data_row][chave] += valor
                acumulados[chave] += valor
                por_data[data_row]["acum_" + str(chave)] = acumulados[chave]
                datas_presentes.add(data_row)

            datas_ordenadas = sorted(datas_presentes)

            # ==================================================
            # BLOCO 2 — Renovação (frente 01) - tabela principal
            # ==================================================
            registros_renovacao = conn.execute(
                text(
                    """
                    SELECT p.data, p.planejado, p.executado
                    FROM prumat_producao p
                    JOIN prumat_frente_producao f ON p.frente_id = f.id
                    WHERE p.eh_id = :eh_id AND f.nome = '01 - Renovação'
                    ORDER BY p.data
                    """
                ),
                {"eh_id": eh_id},
            ).mappings().all()

            previsto_total = 0
            realizado_total = 0
            renovacao_por_data = {}

            for r in registros_renovacao:
                previsto = r["planejado"] or 0
                executado = r["executado"] or 0
                previsto_total += previsto
                realizado_total += executado
                diferenca = realizado_total - previsto_total
                atraso = round(diferenca / 850, 2) if diferenca != 0 else 0

                data_str = str(r["data"])
                dados.append(
                    {
                        "data": data_str,
                        "previsto_dia": previsto,
                        "previsto_total": previsto_total,
                        "realizado_dia": executado,
                        "realizado_total": realizado_total,
                        "diferenca": diferenca,
                        "atraso": atraso,
                    }
                )
                renovacao_por_data[r["data"]] = realizado_total

            # ============================================
            # BLOCO 3 — Cálculos para resumo de frentes
            # ============================================
            # Carregamento (Frente 02)
            saldo_carregamento = 0
            acumulado_carregado_por_data = {}
            saldo_por_data = {}

            for d in datas_ordenadas:
                carregado = por_data[d].get(frentes_map.get("02 - Carregamento_novo"), 0)
                renovado = por_data[d].get(frentes_map.get("01 - Renovação"), 0)

                saldo_carregamento += carregado - renovado
                acumulado_anterior = (
                    list(acumulado_carregado_por_data.values())[-1]
                    if acumulado_carregado_por_data
                    else 0
                )
                acumulado_carregado_por_data[d] = acumulado_anterior + carregado
                saldo_por_data[d] = saldo_carregamento

            # Remoção de grampos (Frente 03)
            saldo_rem_grampos = 0
            acumulado_rem_grampos_por_data = {}
            fa_rem_grampos_por_data = {}

            for d in datas_ordenadas:
                removido = por_data[d].get(frentes_map.get("03 - Remoção_grampos"), 0)
                renovado = por_data[d].get(frentes_map.get("01 - Renovação"), 0)

                saldo_rem_grampos += removido - renovado
                acumulado_anterior = (
                    list(acumulado_rem_grampos_por_data.values())[-1]
                    if acumulado_rem_grampos_por_data
                    else 0
                )
                acumulado_rem_grampos_por_data[d] = acumulado_anterior + removido
                fa_rem_grampos_por_data[d] = saldo_rem_grampos

            # Remoção de galochas (Frente 04)
            saldo_rem_galochas = 0
            acumulado_rem_galochas_por_data = {}
            fa_rem_galochas_por_data = {}

            for d in datas_ordenadas:
                removido = por_data[d].get(frentes_map.get("04 - Remoção_galochas"), 0)
                renovado = por_data[d].get(frentes_map.get("01 - Renovação"), 0)

                saldo_rem_galochas += removido - renovado
                acumulado_anterior = (
                    list(acumulado_rem_galochas_por_data.values())[-1]
                    if acumulado_rem_galochas_por_data
                    else 0
                )
                acumulado_rem_galochas_por_data[d] = acumulado_anterior + removido
                fa_rem_galochas_por_data[d] = saldo_rem_galochas

            # Aplicação de grampos (Frente 06)
            saldo_aplicado_grampos = 0
            acumulado_aplicados_por_data = {}
            aberto_aplicacao_por_data = {}

            for d in datas_ordenadas:
                aplicado = por_data[d].get(frentes_map.get("06 - Aplicação_grampos"), 0)
                renovado = por_data[d].get(frentes_map.get("01 - Renovação"), 0)

                saldo_aplicado_grampos += renovado - aplicado
                acumulado_anterior = (
                    list(acumulado_aplicados_por_data.values())[-1]
                    if acumulado_aplicados_por_data
                    else 0
                )
                acumulado_aplicados_por_data[d] = acumulado_anterior + aplicado
                aberto_aplicacao_por_data[d] = saldo_aplicado_grampos

            # Montagem da tabela consolidada (Resumo Frentes)
            for d in datas_ordenadas:
                rem_grampos = por_data[d].get(frentes_map.get("03 - Remoção_grampos"), 0)
                acum_rem_grampos = acumulado_rem_grampos_por_data.get(d, 0)
                fa_grampos = fa_rem_grampos_por_data.get(d, 0)

                rem_galochas = por_data[d].get(frentes_map.get("04 - Remoção_galochas"), 0)
                acum_rem_galochas = acumulado_rem_galochas_por_data.get(d, 0)
                fa_galochas = fa_rem_galochas_por_data.get(d, 0)

                aplicado = por_data[d].get(frentes_map.get("06 - Aplicação_grampos"), 0)
                acumulado_aplicado = acumulado_aplicados_por_data.get(d, 0)
                aberto = aberto_aplicacao_por_data.get(d, 0)

                linha = {
                    "data": str(d),
                    "carregado": por_data[d].get(
                        frentes_map.get("02 - Carregamento_novo"), 0
                    ),
                    "saldo": saldo_por_data.get(d, 0),
                    "acumulado_carregado": acumulado_carregado_por_data.get(d, 0),
                    "desc_velho": por_data[d].get(
                        frentes_map.get("05 - Descarregamento_velho"), 0
                    ),
                    "desc_novo": por_data[d].get(
                        frentes_map.get("09 - Descarregamento_novo"), 0
                    ),
                    "rem_grampos": rem_grampos,
                    "fa_grampos": fa_grampos,
                    "acum_rem_grampos": acum_rem_grampos,
                    "rem_galochas": rem_galochas,
                    "fa_galochas": fa_galochas,
                    "acum_rem_galochas": acum_rem_galochas,
                    "aplicado": aplicado,
                    "aberto": aberto,
                    "seg_ruins": por_data[d].get(
                        frentes_map.get("08 - Segregação_ruins"), 0
                    ),
                    "seg_bons": por_data[d].get(
                        frentes_map.get("07 - Segregação_bons"), 0
                    ),
                }
                dados_resumo_frentes.append(linha)

            # ===================================================
            # BLOCO 4 — Carregamento Novo (frente 02) + bateria
            # ===================================================
            registros_02 = conn.execute(
                text(
                    """
                    SELECT p.data, p.planejado, p.executado
                    FROM prumat_producao p
                    JOIN prumat_frente_producao f ON p.frente_id = f.id
                    WHERE p.eh_id = :eh_id AND f.nome = '02 - Carregamento_novo'
                    ORDER BY p.data
                    """
                ),
                {"eh_id": eh_id},
            ).mappings().all()

            acumulado_02 = 0
            acumulado_planejado_02 = 0
            plane_total_02 = 0

            for r in registros_02:
                data_row = r["data"]
                previsto = r["planejado"] or 0
                executado = r["executado"] or 0
                acumulado_02 += executado
                acumulado_planejado_02 += previsto
                plane_total_02 += previsto
                realizado_renovacao = renovacao_por_data.get(data_row, 0)

                # Descarregamento velho na mesma data (frente 05)
                desc_row = conn.execute(
                    text(
                        """
                        SELECT p.executado
                        FROM prumat_producao p
                        JOIN prumat_frente_producao f ON p.frente_id = f.id
                        WHERE p.eh_id = :eh_id
                          AND f.nome = '05 - Descarregamento_velho'
                          AND p.data = :data
                        """
                    ),
                    {"eh_id": eh_id, "data": data_row},
                ).mappings().first()

                descarregado = desc_row["executado"] if desc_row else 0

                dados_carregamento.append(
                    {
                        "data": str(data_row),
                        "previsto": previsto,
                        "carregado": executado,
                        "acumulado": acumulado_02,
                        "disponivel": acumulado_02 - realizado_renovacao,
                        "descarregado": descarregado,
                    }
                )

                grafico_barra_carregamento.append(
                    {
                        "data": str(data_row),
                        "planejado": previsto,
                        "executado": executado,
                        "acumulado_planejado": acumulado_planejado_02,
                        "acumulado_executado": acumulado_02,
                    }
                )

            if registros_02 and data_partdiaria:
                registros_filtrados = [
                    r
                    for r in registros_02
                    if str(r["data"]) <= str(data_partdiaria)
                ]
                acumulado_plan = sum(r["planejado"] or 0 for r in registros_filtrados)
                acumulado_exec = sum(r["executado"] or 0 for r in registros_filtrados)

                grafico_bateria_carregamento = {
                    "planejado_total": plane_total_02,
                    "planejado_acumulado": acumulado_plan,
                    "executado_acumulado": acumulado_exec,
                }

            # ==============================================
            # BLOCO 5 — Parte Diária P190-66001 (tabela + gráfico)
            # ==============================================
            if data_partdiaria:
                partes = conn.execute(
                    text(
                        """
                        SELECT
                            pd.hora_inicio,
                            pd.hora_fim,
                            a.nome AS atividade
                        FROM prumat_parte_diaria pd
                        JOIN prumat_atividades a ON pd.atividade_id = a.id
                        JOIN prumat_equipamentos e ON pd.equipamento_id = e.id
                        WHERE e.tag = 'P190-66001'
                          AND pd.data = :data_pd
                        ORDER BY pd.hora_inicio
                        """
                    ),
                    {"data_pd": data_partdiaria},
                ).mappings().all()

                total_por_atividade = {}

                for p in partes:
                    duracao = calcular_duracao(p["hora_inicio"], p["hora_fim"])
                    dados_partdiaria.append(
                        {
                            "atividade": p["atividade"],
                            "hora_inicio": p["hora_inicio"],
                            "hora_fim": p["hora_fim"],
                            "duracao": duracao,
                        }
                    )
                    total_por_atividade[p["atividade"]] = (
                        total_por_atividade.get(p["atividade"], 0) + duracao
                    )

                grafico_atividades = {
                    "labels": list(total_por_atividade.keys()),
                    "tempos": list(total_por_atividade.values()),
                }

            # ====================================
            # BLOCO 6 — Percentuais por Frente (gauges)
            # ====================================
            frentes_icones = {
                "01 - Renovação": ("trem_amarelo.png", "Renovação Dormentes"),
                "02 - Carregamento_novo": ("pa_garfada2.png", "Carregamento Novo"),
                "03 - Remoção_grampos": ("trilho_vertical_madeira.png", "Remoção Grampos"),
                "04 - Remoção_galochas": ("trilho_horizontal_madeira.png", "Remoção Galochas"),
                "06 - Aplicação_grampos": ("trilho_vertical_concreto.png", "Aplicação Grampos"),
                "09 - Descarregamento_novo": ("pa_garfada.png", "Descarregamento Novo"),
            }

            for frente, (icone, titulo) in frentes_icones.items():
                registros = conn.execute(
                    text(
                        """
                        SELECT p.planejado, p.executado
                        FROM prumat_producao p
                        JOIN prumat_frente_producao f ON p.frente_id = f.id
                        WHERE p.eh_id = :eh_id AND f.nome = :frente
                        """
                    ),
                    {"eh_id": eh_id, "frente": frente},
                ).mappings().all()

                total_plan = sum(r["planejado"] or 0 for r in registros)
                total_exec = sum(r["executado"] or 0 for r in registros)
                percentual = round((total_exec / total_plan) * 100, 1) if total_plan else 0

                percentuais_graficos[frente] = {
                    "icone": icone,
                    "titulo": titulo,
                    "percentual_executado": percentual,
                }

    # Renderiza o template com todos os blocos
    return render_template(
        "operacao/producao.html",
        ehs=ehs,
        eh_id=int(eh_id) if eh_id else None,
        dados=dados,
        data_partdiaria=data_partdiaria or "",
        dados_partdiaria=dados_partdiaria,
        grafico_atividades=grafico_atividades,
        dados_carregamento=dados_carregamento,
        grafico_barra_carregamento=grafico_barra_carregamento,
        grafico_bateria_carregamento=grafico_bateria_carregamento,
        dados_resumo_frentes=dados_resumo_frentes,
        percentuais_graficos=percentuais_graficos,
    )
