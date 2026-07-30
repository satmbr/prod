import unittest

from routes.operacao_producao import calcular_saldos


class SaldosProducaoTests(unittest.TestCase):
    def setUp(self):
        self.zero = {
            "PULMAO_CHAO": 0,
            "NOVOS_VAGOES": 0,
            "GRAMPOS_ABERTOS": 0,
            "GALOCHAS_ABERTAS": 0,
            "PREGACAO_ABERTA": 0,
            "VELHOS_VAGOES": 0,
        }

    def producao(self, **valores):
        base = {
            "DESCARREGAMENTO_NOVO": 0,
            "CARREGAMENTO_NOVO": 0,
            "RENOVACAO": 0,
            "REMOCAO_GRAMPOS": 0,
            "REMOCAO_GALOCHAS": 0,
            "APLICACAO_GRAMPOS": 0,
            "DESCARREGAMENTO_VELHO": 0,
        }
        base.update(valores)
        return base

    def test_renovacao_consume_frente_aberta_de_grampos(self):
        inicial = {**self.zero, "GRAMPOS_ABERTOS": 1000}
        final = calcular_saldos(inicial, self.producao(RENOVACAO=500))
        self.assertEqual(final["GRAMPOS_ABERTOS"], 500)

    def test_pulmao_e_vagoes_seguem_fluxo_fisico(self):
        inicial = {**self.zero, "PULMAO_CHAO": 3000}
        final = calcular_saldos(
            inicial,
            self.producao(CARREGAMENTO_NOVO=2000, RENOVACAO=1000),
        )
        self.assertEqual(final["PULMAO_CHAO"], 1000)
        self.assertEqual(final["NOVOS_VAGOES"], 1000)

    def test_renovacao_gera_pregacao_e_dormente_velho_em_aberto(self):
        final = calcular_saldos(self.zero, self.producao(RENOVACAO=850))
        self.assertEqual(final["PREGACAO_ABERTA"], 850)
        self.assertEqual(final["VELHOS_VAGOES"], 850)

    def test_funcao_nao_altera_saldo_original(self):
        inicial = dict(self.zero)
        calcular_saldos(inicial, self.producao(DESCARREGAMENTO_NOVO=200))
        self.assertEqual(inicial, self.zero)


if __name__ == "__main__":
    unittest.main()
