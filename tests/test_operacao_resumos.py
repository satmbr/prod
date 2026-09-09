import unittest
from datetime import date
from pathlib import Path

from routes.operacao_resumos import (
    _montar_tabela_diaria,
    _resumir_producao,
    calcular_indicadores_maquina,
    classificar_atividade,
)


class ResumoProducaoTests(unittest.TestCase):
    def linhas(self):
        return [
            {
                "eh_id": 1,
                "eh": "EH 2026",
                "frente_id": 10,
                "frente": "01 - Renovação",
                "codigo": "RENOVACAO",
                "data": date(2026, 1, 1),
                "planejado": 100,
                "realizado": 80,
            },
            {
                "eh_id": 1,
                "eh": "EH 2026",
                "frente_id": 11,
                "frente": "02 - Carregamento",
                "codigo": "CARREGAMENTO_NOVO",
                "data": date(2026, 1, 1),
                "planejado": 50,
                "realizado": 45,
            },
        ]

    def test_plano_finalizado_nao_recebe_projecao(self):
        resumo = _resumir_producao(self.linhas(), [1])
        plano = resumo["planos"][0]
        self.assertTrue(plano["finalizado"])
        self.assertIsNone(plano["data_projetada"])
        self.assertIsNone(plano["ritmo_necessario"])

    def test_velocidade_usa_somente_producao_da_renovacao(self):
        resumo = _resumir_producao(self.linhas(), [])
        self.assertEqual(resumo["renovacao_por_data"]["2026-01-01"], 80)
        self.assertEqual(resumo["kpis"]["realizado"], 125)

    def test_totais_consolidam_todas_as_frentes_selecionadas(self):
        resumo = _resumir_producao(self.linhas(), [])
        self.assertEqual(resumo["kpis"]["planejado"], 150)
        self.assertEqual(resumo["kpis"]["realizado"], 125)
        self.assertEqual(resumo["kpis"]["diferenca"], -25)

    def test_tabela_diaria_segue_modelo_e_preenche_dias_sem_lancamento(self):
        linhas = self.linhas()
        linhas.append(
            {
                **linhas[0],
                "data": date(2026, 1, 3),
                "planejado": 100,
                "realizado": 120,
            }
        )
        tabela = _montar_tabela_diaria(linhas, [])
        self.assertEqual(len(tabela), 3)
        self.assertEqual(tabela[1]["data"], date(2026, 1, 2))
        self.assertEqual(tabela[1]["planejado_dia"], 0)
        self.assertEqual(tabela[1]["planejado_total"], 150)
        self.assertEqual(tabela[1]["realizado_total"], 125)
        self.assertIn("dia_semana", tabela[0])
        self.assertIn("atraso_dias", tabela[0])

    def test_tabela_inclui_impactos_da_eh_e_data(self):
        impacto = {
            "eh_id": 1,
            "data": date(2026, 1, 1),
            "frente": "01 - Renovação",
            "descricao": "Chuva forte",
            "minutos_perdidos": 45,
        }
        tabela = _montar_tabela_diaria(self.linhas(), [impacto])
        self.assertIn("Chuva forte", tabela[0]["observacoes"])
        self.assertIn("45 min", tabela[0]["observacoes"])

    def test_impacto_e_observacao_usam_linhas_separadas(self):
        impacto = {
            "eh_id": 1,
            "data": date(2026, 1, 1),
            "frente": "01 - Renovação",
            "descricao": "Chuva forte",
            "minutos_perdidos": 45,
        }
        observacao = {
            "eh_id": 1,
            "data": date(2026, 1, 1),
            "frente": "01 - Renovação",
            "observacao": "Equipe liberada às 08h",
        }
        tabela = _montar_tabela_diaria(self.linhas(), [impacto], [observacao])
        self.assertIn("Impacto", tabela[0]["observacoes"])
        self.assertEqual(len(tabela[0]["complementos"]), 1)
        self.assertEqual(tabela[0]["complementos"][0], "Equipe liberada às 08h")

    def test_observacao_sem_impacto_aparece_sem_prefixo(self):
        observacao = {
            "eh_id": 1,
            "data": date(2026, 1, 1),
            "frente": "01 - Renovação",
            "observacao": "Realizada entrada da P190.",
        }
        tabela = _montar_tabela_diaria(self.linhas(), [], [observacao])
        self.assertEqual(tabela[0]["observacoes"], "Realizada entrada da P190.")


class ResumoMaquinasTests(unittest.TestCase):
    def test_classifica_atividades_com_acentos_e_variacoes(self):
        self.assertEqual(classificar_atividade("Renovação"), "producao")
        self.assertEqual(classificar_atividade("Manutenção Corretiva"), "corretiva")
        self.assertEqual(classificar_atividade("Preventiva programada"), "preventiva")
        self.assertEqual(classificar_atividade("Deslocamento"), "outras")

    def test_disponibilidade_desconta_corretiva_e_preventiva(self):
        indicadores = calcular_indicadores_maquina(600, 60, 40, 300)
        self.assertAlmostEqual(indicadores["disponibilidade"], 83.333333, places=5)
        self.assertAlmostEqual(indicadores["utilizacao"], 60.0)
        self.assertAlmostEqual(indicadores["horas_producao"], 5.0)


class ResumoTemplateTests(unittest.TestCase):
    def setUp(self):
        raiz = Path(__file__).resolve().parents[1]
        self.template = (raiz / "templates" / "operacao" / "resumos.html").read_text(encoding="utf-8")

    def test_pergunta_se_plano_foi_finalizado(self):
        self.assertIn('name="finalizada_ids"', self.template)
        self.assertIn("Plano finalizado", self.template)
        self.assertIn("sem tendência ou projeção", self.template)

    def test_nao_exibe_velocidade_planejada(self):
        self.assertNotIn("Velocidade planejada", self.template)
        self.assertIn("Velocidade consolidada", self.template)
        self.assertIn("Velocidade média diária", self.template)

    def test_impactos_sao_condicionais(self):
        self.assertIn("{% if r.impactos %}", self.template)

    def test_exibe_tabela_modelo_e_novos_graficos(self):
        self.assertIn("Observações / impactos", self.template)
        self.assertIn('id="chart-mesclado"', self.template)
        self.assertIn('id="chart-frentes-acumulado"', self.template)
        self.assertIn('id="chart-parte-tempos"', self.template)
        self.assertIn('id="chart-parte-velocidade"', self.template)

    def test_usa_paleta_do_site_e_resultado_por_frente_compacto(self):
        self.assertNotIn("rgba(110,173,69", self.template)
        self.assertNotIn("rgba(240,122,41", self.template)
        self.assertIn("front-result-grid", self.template)
        self.assertIn("#16324f", self.template)
        self.assertIn("#246b9e", self.template)
        self.assertIn("#0f8b8d", self.template)

    def test_tabelas_centralizadas_sem_barra_de_rolagem(self):
        self.assertIn("overflow:visible", self.template)
        self.assertIn("text-align:center", self.template)
        self.assertNotIn("max-height:470px", self.template)

    def test_tabela_diaria_pode_ocultar_dias_totalmente_vazios(self):
        self.assertIn("production-daily-table", self.template)
        self.assertIn("empty-production-day", self.template)
        self.assertIn("createEmptyDaysToggle", self.template)
        self.assertIn("Ocultar dias sem planejamento, execução, observação ou impacto", self.template)

    def test_graficos_tem_valores_e_todos_os_elementos_podem_ser_copiados(self):
        self.assertIn("valueLabelsPlugin", self.template)
        self.assertIn("copyElementAsImage", self.template)
        self.assertIn('backgroundColor:null', self.template)
        self.assertIn('.resumo-page canvas, .resumo-page table', self.template)
        self.assertIn("ClipboardItem", self.template)

    def test_graficos_permitam_alternar_valores_de_linhas_e_barras(self):
        self.assertIn("$showLineValues", self.template)
        self.assertIn("$showBarValues", self.template)
        self.assertIn("Ligar ou desligar valores das linhas", self.template)
        self.assertIn("Ligar ou desligar valores das barras", self.template)

    def test_cartoes_de_plano_e_maquina_tambem_podem_ser_copiados(self):
        self.assertIn(".resumo-page .plan-card", self.template)
        self.assertIn("card-copy-host", self.template)

    def test_resultado_consolidado_pode_ser_copiado_em_conjunto(self):
        self.assertIn("consolidated-kpis", self.template)
        self.assertIn(".resumo-page .consolidated-kpis", self.template)
        self.assertNotIn(".resumo-page .kpi, .resumo-page .plan-card", self.template)

    def test_tabela_de_atividades_alinha_nome_a_esquerda_e_numeros_ao_centro(self):
        self.assertIn("activity-table", self.template)
        self.assertIn("activity-name-value", self.template)
        self.assertIn("text-align:left !important", self.template)


class RegistroObservacoesTests(unittest.TestCase):
    def setUp(self):
        raiz = Path(__file__).resolve().parents[1]
        self.registro = (raiz / "templates" / "operacao" / "registro.html").read_text(encoding="utf-8")
        self.rotas = (raiz / "routes" / "operacao.py").read_text(encoding="utf-8")
        self.migracao = (raiz / "migrations" / "019_operacao_observacoes.sql").read_text(encoding="utf-8")

    def test_registro_possui_formulario_de_observacao(self):
        self.assertIn("Observações para o resumo", self.registro)
        self.assertIn("operacao.producao_observacao_create", self.registro)
        self.assertIn('name="observacao"', self.registro)
        self.assertIn('<select name="eh_id" required>', self.registro)

    def test_rotas_criam_e_excluem_observacoes(self):
        self.assertIn("def producao_observacao_create", self.rotas)
        self.assertIn("def producao_observacao_delete", self.rotas)

    def test_migracao_vincula_observacao_a_eh_e_frente(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS operacao_observacao", self.migracao)
        self.assertIn("REFERENCES entre_house", self.migracao)
        self.assertIn("REFERENCES frente_equipe", self.migracao)


if __name__ == "__main__":
    unittest.main()
