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

    def test_revisao_oferece_desconto_ajuste_aceite_e_contraproposta(self):
        self.assertIn('acao in {"revisar", "desconto"}', self.rota)
        self.assertIn('acao == "propor_ajuste"', self.rota)
        self.assertIn("def aceitar_ajuste", self.rota)
        portal = (ROOT / "templates" / "fornecedores" / "portal_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("Aceitar ajuste", portal)
        self.assertIn("Propor valores", portal)
        self.assertIn("Ajustar valores", portal)

    def test_negociacao_mostra_apenas_orcamento_atual(self):
        detalhe = (ROOT / "templates" / "fornecedores" / "portal_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("Orçamento atual", detalhe)
        self.assertNotIn("Seu orçamento · versão", detalhe)
        migracao = (ROOT / "migrations" / "027_fornecedores_negociacao_viva.sql").read_text(encoding="utf-8")
        self.assertIn("valor_unitario_proposto_admin", migracao)

    def test_cancelamento_direto_ou_com_aceite_e_exclusao_posterior(self):
        migracao = (ROOT / "migrations" / "028_fornecedores_cancelamento.sql").read_text(encoding="utf-8")
        for termo in ("CANCELAMENTO_SOLICITADO", "CANCELADA", "CANCELADO", "status_antes_cancelamento"):
            self.assertIn(termo, migracao)
        self.assertIn("def cancelar_solicitacao", self.rota)
        self.assertIn("def responder_cancelamento", self.rota)
        self.assertIn("def excluir_solicitacao", self.rota)
        self.assertIn('solicitacao["status"] != "CANCELADA"', self.rota)

    def test_fornecedor_so_responde_cancelamento_e_nao_exclui(self):
        portal = (ROOT / "templates" / "fornecedores" / "portal_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("Aceitar cancelamento", portal)
        self.assertIn("Recusar cancelamento", portal)
        self.assertNotIn("Excluir definitivamente", portal)
        self.assertNotIn("Cancelar solicitação", portal)

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
        self.assertIn("/fornecedores/solicitacoes/<int:solicitacao_id>/cancelar", regras)
        self.assertIn("/fornecedores/solicitacoes/<int:solicitacao_id>/excluir", regras)
        self.assertIn("/portal-fornecedor/solicitacoes/<int:solicitacao_id>/responder-cancelamento", regras)


if __name__ == "__main__":
    unittest.main()
