# routes/operacao.py

from flask import Blueprint, render_template, request
import psycopg2
import psycopg2.extras
from models import get_db_connection
from utils.calcular_duracao import calcular_duracao
from utils import nivel_requerido
from collections import defaultdict

# Se no seu projeto o blueprint já existir, reaproveite o existente.
# Exemplo, se já tiver:
#   operacao_bp = Blueprint('operacao', __name__, url_prefix='/operacao')
# então remova esta linha abaixo e use o nome que já existe.
operacao_bp = Blueprint('operacao', __name__, url_prefix='/operacao')


@operacao_bp.route('/producao')
@nivel_requerido('admin', 'gerente', 'tecnico', 'planejador', 'visualizador')
def producao():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # EHs para o filtro
    cur.execute("SELECT * FROM prumat_eh ORDER BY nome")
    ehs = cur.fetchall()

    eh_id = request.args.get('eh_id')
    data_partdiaria = request.args.get('data_partdiaria')

    dados = []
    dados_partdiaria = []
    grafico_atividades = {'labels': [], 'tempos': []}
    dados_carregamento = []
    grafico_barra_carregamento = []
    grafico_bateria_carregamento = {}
    dados_resumo_frentes = []
    percentuais_graficos = {}

    if eh_id:
        # === BLOCO PRINCIPAL DE PRODUÇÃO (Renovação + Resumo frentes) ===
        # Buscar frentes com produção para essa EH
        cur.execute(
            '''
            SELECT DISTINCT f.nome, f.id
            FROM prumat_frente_producao f
            JOIN prumat_producao p ON p.frente_id = f.id
            WHERE p.eh_id = %s
            ''',
            (eh_id,)
        )
        frentes = cur.fetchall()

        # Frentes que serão usadas na tabela consolidada
        frentes_interessadas = [
            '01 - Renovação',
            '02 - Carregamento_novo',
            '03 - Remoção_grampos',
            '04 - Remoção_galochas',
            '05 - Descarregamento_velho',
            '06 - Aplicação_grampos',
            '07 - Segregação_bons',
            '08 - Segregação_ruins',
            '09 - Descarregamento_novo'
        ]

        # Mapear nomes para IDs
        frentes_map = {}
        for frente in frentes:
            if frente['nome'] in frentes_interessadas:
                frentes_map[frente['nome']] = frente['id']

        # Buscar registros de produção por frente
        registros_frentes = []
        if frentes_map:
            cur.execute(
                f'''
                SELECT f.nome as frente, p.data, p.executado
                FROM prumat_producao p
                JOIN prumat_frente_producao f ON p.frente_id = f.id
                WHERE p.eh_id = %s AND f.nome IN ({','.join(['%s'] * len(frentes_map))})
                ORDER BY p.data
                ''',
                [eh_id] + list(frentes_map.keys())
            )
            registros_frentes = cur.fetchall()

        # Inicializar estruturas
        por_data = defaultdict(lambda: {k: 0 for k in frentes_map.values()})
        acumulados = {k: 0 for k in frentes_map.values()}
        datas_presentes = set()

        # Preencher registros por data e frente
        for row in registros_frentes:
            frente = row['frente']
            data = row['data']
            valor = row['executado'] or 0

            if frente not in frentes_map:
                continue

            chave = frentes_map[frente]
            por_data[data][chave] += valor
            acumulados[chave] += valor
            por_data[data]['acum_' + str(chave)] = acumulados[chave]
            datas_presentes.add(data)

        # Acumulado específico da frente "01 - Renovação"
        acumulado_renovacao = 0
        renovacao_acumulado_por_data = {}
        cur.execute(
            '''
            SELECT p.data, p.planejado, p.executado
            FROM prumat_producao p
            JOIN prumat_frente_producao f ON p.frente_id = f.id
            WHERE p.eh_id = %s AND f.nome = '01 - Renovação'
            ORDER BY p.data
            ''',
            (eh_id,)
        )
        registros_renovacao = cur.fetchall()
        acumulado_renovacao = 0
        renovacao_acumulado_por_data = {}
        for r in registros_renovacao:
            data = r['data']
            acumulado_renovacao += r['executado'] or 0
            renovacao_acumulado_por_data[data] = acumulado_renovacao

        datas_ordenadas = sorted(datas_presentes)

        # === Cálculos de saldo / acumulado por frente ===

        # Carregamento (Frente 02)
        saldo_carregamento = 0
        acumulado_carregado_por_data = {}
        saldo_por_data = {}

        for data in datas_ordenadas:
            carregado = por_data[data].get(frentes_map.get('02 - Carregamento_novo'), 0)
            renovado = por_data[data].get(frentes_map.get('01 - Renovação'), 0)

            saldo_carregamento += carregado - renovado
            acumulado_anterior = list(acumulado_carregado_por_data.values())[-1] if acumulado_carregado_por_data else 0
            acumulado_carregado_por_data[data] = acumulado_anterior + carregado
            saldo_por_data[data] = saldo_carregamento

        # Remoção de grampos (Frente 03)
        saldo_rem_grampos = 0
        acumulado_rem_grampos_por_data = {}
        fa_rem_grampos_por_data = {}

        for data in datas_ordenadas:
            removido = por_data[data].get(frentes_map.get('03 - Remoção_grampos'), 0)
            renovado = por_data[data].get(frentes_map.get('01 - Renovação'), 0)

            saldo_rem_grampos += removido - renovado
            acumulado_anterior = list(acumulado_rem_grampos_por_data.values())[-1] if acumulado_rem_grampos_por_data else 0
            acumulado_rem_grampos_por_data[data] = acumulado_anterior + removido
            fa_rem_grampos_por_data[data] = saldo_rem_grampos

        # Remoção de galochas (Frente 04)
        saldo_rem_galochas = 0
        acumulado_rem_galochas_por_data = {}
        fa_rem_galochas_por_data = {}

        for data in datas_ordenadas:
            removido = por_data[data].get(frentes_map.get('04 - Remoção_galochas'), 0)
            renovado = por_data[data].get(frentes_map.get('01 - Renovação'), 0)

            saldo_rem_galochas += removido - renovado
            acumulado_anterior = list(acumulado_rem_galochas_por_data.values())[-1] if acumulado_rem_galochas_por_data else 0
            acumulado_rem_galochas_por_data[data] = acumulado_anterior + removido
            fa_rem_galochas_por_data[data] = saldo_rem_galochas

        # Aplicação de grampos (Frente 06)
        saldo_aplicado_grampos = 0
        acumulado_aplicados_por_data = {}
        aberto_aplicacao_por_data = {}

        for data in datas_ordenadas:
            aplicado = por_data[data].get(frentes_map.get('06 - Aplicação_grampos'), 0)
            renovado = por_data[data].get(frentes_map.get('01 - Renovação'), 0)

            saldo_aplicado_grampos += renovado - aplicado
            acumulado_anterior = list(acumulado_aplicados_por_data.values())[-1] if acumulado_aplicados_por_data else 0
            acumulado_aplicados_por_data[data] = acumulado_anterior + aplicado
            aberto_aplicacao_por_data[data] = saldo_aplicado_grampos

        # Montagem da tabela consolidada (Resumo Frentes)
        for data in datas_ordenadas:
            rem_grampos = por_data[data].get(frentes_map.get('03 - Remoção_grampos'), 0)
            acum_rem_grampos = acumulado_rem_grampos_por_data.get(data, 0)
            fa_grampos = fa_rem_grampos_por_data.get(data, 0)

            rem_galochas = por_data[data].get(frentes_map.get('04 - Remoção_galochas'), 0)
            acum_rem_galochas = acumulado_rem_galochas_por_data.get(data, 0)
            fa_galochas = fa_rem_galochas_por_data.get(data, 0)

            aplicado = por_data[data].get(frentes_map.get('06 - Aplicação_grampos'), 0)
            acumulado_aplicado = acumulado_aplicados_por_data.get(data, 0)
            aberto = aberto_aplicacao_por_data.get(data, 0)

            linha = {
                'data': str(data),
                'carregado': por_data[data].get(frentes_map.get('02 - Carregamento_novo'), 0),
                'saldo': saldo_por_data.get(data, 0),
                'acumulado_carregado': acumulado_carregado_por_data.get(data, 0),
                'desc_velho': por_data[data].get(frentes_map.get('05 - Descarregamento_velho'), 0),
                'desc_novo': por_data[data].get(frentes_map.get('09 - Descarregamento_novo'), 0),
                'rem_grampos': rem_grampos,
                'fa_grampos': fa_grampos,
                'acum_rem_grampos': acum_rem_grampos,
                'rem_galochas': rem_galochas,
                'fa_galochas': fa_galochas,
                'acum_rem_galochas': acum_rem_galochas,
                'aplicado': aplicado,
                'aberto': aberto,
                'seg_ruins': por_data[data].get(frentes_map.get('08 - Segregação_ruins'), 0),
                'seg_bons': por_data[data].get(frentes_map.get('07 - Segregação_bons'), 0)
            }
            dados_resumo_frentes.append(linha)

        # === Tabela + gráfico de Renovação (Frente 01) ===
        previsto_total = 0
        realizado_total = 0
        renovacao_por_data = {}
        for r in registros_renovacao:
            previsto_total += r['planejado'] or 0
            realizado_total += r['executado'] or 0
            diferenca = realizado_total - previsto_total
            atraso = round(diferenca / 850, 2) if diferenca != 0 else 0
            dados.append({
                'data': str(r['data']),
                'previsto_dia': r['planejado'],
                'previsto_total': previsto_total,
                'realizado_dia': r['executado'],
                'realizado_total': realizado_total,
                'diferenca': diferenca,
                'atraso': atraso
            })
            renovacao_por_data[r['data']] = realizado_total

        # === Carregamento Novo - dados para tabela e gráfico ===
        cur.execute(
            '''
            SELECT p.data, p.planejado, p.executado
            FROM prumat_producao p
            JOIN prumat_frente_producao f ON p.frente_id = f.id
            WHERE p.eh_id = %s AND f.nome = '02 - Carregamento_novo'
            ORDER BY p.data
            ''',
            (eh_id,)
        )
        registros_02 = cur.fetchall()

        acumulado_02 = 0
        acumulado_planejado_02 = 0
        plane_total_02 = 0

        for r in registros_02:
            data = r['data']
            previsto = r['planejado'] or 0
            executado = r['executado'] or 0
            acumulado_02 += executado
            acumulado_planejado_02 += previsto
            plane_total_02 += previsto
            realizado_renovacao = renovacao_por_data.get(data, 0)

            cur.execute(
                '''
                SELECT executado FROM prumat_producao p
                JOIN prumat_frente_producao f ON p.frente_id = f.id
                WHERE p.eh_id = %s AND f.nome = '05 - Descarregamento_velho' AND p.data = %s
                ''',
                (eh_id, data)
            )
            descarregado = cur.fetchone()

            dados_carregamento.append({
                'data': str(data),
                'previsto': previsto,
                'carregado': executado,
                'acumulado': acumulado_02,
                'disponivel': acumulado_02 - realizado_renovacao,
                'descarregado': descarregado['executado'] if descarregado else 0
            })

            grafico_barra_carregamento.append({
                'data': str(data),
                'planejado': previsto,
                'executado': executado,
                'acumulado_planejado': acumulado_planejado_02,
                'acumulado_executado': acumulado_02
            })

        # === Gráfico de Bateria (Carregamento) ===
        if data_partdiaria:
            registros_filtrados = [r for r in registros_02 if str(r['data']) <= data_partdiaria]
            acumulado_plan = sum(r['planejado'] or 0 for r in registros_filtrados)
            acumulado_exec = sum(r['executado'] or 0 for r in registros_filtrados)

            grafico_bateria_carregamento = {
                'planejado_total': plane_total_02,
                'planejado_acumulado': acumulado_plan,
                'executado_acumulado': acumulado_exec
            }

        # === Parte Diária P190-66001 ===
        if data_partdiaria:
            cur.execute(
                '''
                SELECT pd.hora_inicio, pd.hora_fim, a.nome as atividade
                FROM prumat_parte_diaria pd
                JOIN prumat_atividades a ON pd.atividade_id = a.id
                JOIN prumat_equipamentos e ON pd.equipamento_id = e.id
                WHERE e.tag = 'P190-66001' AND pd.data = %s
                ORDER BY pd.hora_inicio
                ''',
                (data_partdiaria,)
            )
            partes = cur.fetchall()

            total_por_atividade = {}
            for p in partes:
                duracao = calcular_duracao(p['hora_inicio'], p['hora_fim'])
                dados_partdiaria.append({
                    'atividade': p['atividade'],
                    'hora_inicio': p['hora_inicio'],
                    'hora_fim': p['hora_fim'],
                    'duracao': duracao
                })
                total_por_atividade[p['atividade']] = total_por_atividade.get(p['atividade'], 0) + duracao

            grafico_atividades = {
                'labels': list(total_por_atividade.keys()),
                'tempos': list(total_por_atividade.values())
            }

        # === Percentuais por Frente (Gauges) ===
        frentes_icones = {
            '01 - Renovação': ('trem_amarelo.png', 'Renovação Dormentes'),
            '02 - Carregamento_novo': ('pa_garfada2.png', 'Carregamento Novo'),
            '03 - Remoção_grampos': ('trilho_vertical_madeira.png', 'Remoção Grampos'),
            '04 - Remoção_galochas': ('trilho_horizontal_madeira.png', 'Remoção Galochas'),
            '06 - Aplicação_grampos': ('trilho_vertical_concreto.png', 'Aplicação Grampos'),
            '09 - Descarregamento_novo': ('pa_garfada.png', 'Descarregamento Novo')
        }

        for frente, (icone, titulo) in frentes_icones.items():
            cur.execute(
                '''
                SELECT planejado, executado FROM prumat_producao p
                JOIN prumat_frente_producao f ON p.frente_id = f.id
                WHERE p.eh_id = %s AND f.nome = %s
                ''',
                (eh_id, frente)
            )
            registros = cur.fetchall()

            total_plan = sum(r['planejado'] or 0 for r in registros)
            total_exec = sum(r['executado'] or 0 for r in registros)
            percentual = round((total_exec / total_plan) * 100, 1) if total_plan else 0

            percentuais_graficos[frente] = {
                'icone': icone,
                'titulo': titulo,
                'percentual_executado': percentual
            }

    conn.close()

    return render_template(
        'operacao/producao.html',
        ehs=ehs,
        eh_id=int(eh_id) if eh_id else None,
        dados=dados,
        data_partdiaria=data_partdiaria or '',
        dados_partdiaria=dados_partdiaria,
        grafico_atividades=grafico_atividades,
        dados_carregamento=dados_carregamento,
        grafico_barra_carregamento=grafico_barra_carregamento,
        grafico_bateria_carregamento=grafico_bateria_carregamento,
        dados_resumo_frentes=dados_resumo_frentes,
        percentuais_graficos=percentuais_graficos
    )
