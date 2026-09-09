import unittest
from datetime import date
from pathlib import Path

from routes.operacao_resumos import (
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


if __name__ == "__main__":
    unittest.main()
