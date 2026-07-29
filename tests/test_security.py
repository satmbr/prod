import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "chave-exclusiva-dos-testes-locais")

from app import app
from routes.financeiro_dois_reembolsos_routes import (
    _candidatos_caminho_anexo_reembolso,
)
from routes.financeiro_dois_routes import _resolver_candidatos_arquivo


class SecurityRegressionTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()

    def test_login_de_usuario_inexistente_nao_retorna_erro_500(self):
        engine = MagicMock()
        resultado = (
            engine.connect.return_value.__enter__.return_value
            .execute.return_value.mappings.return_value
        )
        resultado.first.return_value = None

        with patch("routes.auth.get_engine", return_value=engine):
            resposta = self.client.post(
                "/auth/login",
                data={"username": "nao-existe", "senha": "invalida"},
            )

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Usuário ou senha inválidos".encode(), resposta.data)

    def test_usuario_com_apenas_visualizacao_nao_altera_financeiro(self):
        with self.client.session_transaction() as sessao:
            sessao["usuario_id"] = 1
            sessao["usuario_nome"] = "Teste"
            sessao["permissoes"] = ["financeiro:visualizar"]

        resposta = self.client.post("/financeiro/om/nova", data={})
        self.assertEqual(resposta.status_code, 403)

    def test_uploads_nao_sao_expostos_pela_rota_estatica(self):
        resposta = self.client.get("/static/uploads/financeiro2/segredo.pdf")
        self.assertEqual(resposta.status_code, 404)

    def test_caminhos_de_anexos_descartam_diretorios_fornecidos(self):
        with app.app_context():
            candidatos = _resolver_candidatos_arquivo(
                "../../app.py",
                ["despesas"],
            )
            candidatos_reembolso = _candidatos_caminho_anexo_reembolso(
                "/etc/passwd"
            )

        self.assertTrue(candidatos)
        self.assertTrue(all(os.path.basename(item) == "app.py" for item in candidatos))
        self.assertTrue(candidatos_reembolso)
        self.assertTrue(
            all(os.path.basename(item) == "passwd" for item in candidatos_reembolso)
        )


if __name__ == "__main__":
    unittest.main()
