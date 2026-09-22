import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FornecedoresEstruturaTests(unittest.TestCase):
    def setUp(self):
        self.sql = (ROOT / "migrations" / "026_fornecedores_portal.sql").read_text(encoding="utf-8")
        self.rota = (ROOT / "routes" / "fornecedores.py").read_text(encoding="utf-8")

    def test_portal_tem_link_exclusivo_revogavel(self):
        self.assertIn("portal_token VARCHAR(64) NOT NULL UNIQUE", self.sql)
        self.assertIn("portal_ativo BOOLEAN NOT NULL DEFAULT FALSE", self.sql)
        self.assertIn("def novo_link", self.rota)

    def test_orcamentos_sao_versionados_e_preservam_valor_original(self):
        self.assertIn("UNIQUE (destino_id, versao)", self.sql)
        self.assertIn("valor_unitario_original", self.sql)
        self.assertIn("valor_unitario_ajustado", self.sql)
        self.assertIn("valor_unitario_ajustado >= valor_unitario_original", self.sql)

    def test_fluxo_contem_revisao_execucao_e_fechamento(self):
        for termo in ("REVISAO_SOLICITADA", "EM_EXECUCAO", "AGUARDANDO_FECHAMENTO", "FECHADA"):
            self.assertIn(termo, self.sql)
        for categoria in ("SOLICITACAO", "ORCAMENTO", "EVIDENCIA", "NOTA_FISCAL"):
            self.assertIn(categoria, self.sql)

    def test_aprovacao_impede_reducao_e_calcula_bdi(self):
        self.assertIn("só pode manter ou aumentar valores", self.rota)
        self.assertIn("bdi_valor =", self.rota)
        self.assertIn("total = subtotal + bdi_valor", self.rota)

    def test_portal_nao_libera_sistema_principal(self):
        fonte = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('request.blueprint == "portal_fornecedor"', fonte)
        self.assertIn("portal_required", self.rota)

    def test_rotas_estao_registradas(self):
        os.environ.setdefault("SECRET_KEY", "teste")
        from app import app
        regras = {r.rule for r in app.url_map.iter_rules()}
        self.assertIn("/fornecedores", regras)
        self.assertIn("/fornecedores/solicitacoes", regras)
        self.assertIn("/portal-fornecedor", regras)
        self.assertIn("/portal-fornecedor/acesso/<token>", regras)


if __name__ == "__main__":
    unittest.main()
