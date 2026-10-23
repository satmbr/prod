import os
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch

from routes.financeiro_novo.services.pagamentos_bucket import (
    PagamentosStorageErro,
    _s3,
    baixar_arquivo,
    configuracao_bucket,
    limpar_nome_arquivo,
    listar_arquivos,
)


class FakeS3:
    def __init__(self):
        self.corpo = BytesIO(b"%PDF-1.4\nrecibo")

    def list_objects_v2(self, **_params):
        return {"Contents": [
            {
                "Key": "perfil_pagamentos/7/novas_contas/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/100,00 hospedagem.pdf",
                "Size": 1024,
                "LastModified": datetime(2026, 9, 6, tzinfo=timezone.utc),
            },
            {"Key": "perfil_pagamentos/7/novas_contas/arquivo-fora-do-padrao.pdf", "Size": 3},
        ]}

    def get_object(self, **_params):
        return {"Body": self.corpo, "ContentType": "application/pdf"}


class PagamentosBucketTests(unittest.TestCase):
    def test_aceita_variaveis_nativas_do_railway(self):
        ambiente = {
            "BUCKET": "pagamentos-abc",
            "ENDPOINT": "https://t3.storageapi.dev",
            "ACCESS_KEY_ID": "chave",
            "SECRET_ACCESS_KEY": "segredo",
            "REGION": "auto",
        }
        with patch.dict(os.environ, ambiente, clear=True):
            cfg = configuracao_bucket()
        self.assertEqual(cfg["bucket"], "pagamentos-abc")
        self.assertEqual(cfg["region"], "auto")

    def test_nao_mistura_chave_nativa_com_segredo_aws(self):
        with patch.dict(os.environ, {
            "BUCKET": "bucket", "ENDPOINT": "https://example.com",
            "ACCESS_KEY_ID": "chave-nativa", "AWS_SECRET_ACCESS_KEY": "segredo-aws",
        }, clear=True):
            with self.assertRaisesRegex(PagamentosStorageErro, "Não misture"):
                configuracao_bucket()

    def test_aceita_pares_completos_dos_aliases(self):
        for chave, segredo in (
            ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
            ("BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY"),
        ):
            with self.subTest(chave=chave), patch.dict(os.environ, {
                "BUCKET": "bucket", "ENDPOINT": "https://example.com",
                chave: "chave", segredo: "segredo",
            }, clear=True):
                cfg = configuracao_bucket()
                self.assertEqual((cfg["access_key"], cfg["secret_key"]), ("chave", "segredo"))

    def test_diagnostico_assinatura_na_listagem_e_envio(self):
        from botocore.stub import Stubber
        from botocore.exceptions import ClientError
        with patch.dict(os.environ, {
            "BUCKET": "bucket", "ENDPOINT": "https://example.com",
            "ACCESS_KEY_ID": "chave", "SECRET_ACCESS_KEY": "segredo",
        }, clear=True):
            cliente, bucket = _s3()
        with Stubber(cliente) as stub:
            for operacao, params in (
                ("list_objects_v2", {"Bucket": bucket}),
                ("put_object", {"Bucket": bucket, "Key": "teste.pdf", "Body": b"pdf"}),
            ):
                stub.add_client_error(operacao, service_error_code="SignatureDoesNotMatch")
                with self.subTest(operacao=operacao):
                    with self.assertRaisesRegex(PagamentosStorageErro, "aba Credentials"):
                        getattr(cliente, operacao)(**params)
            stub.add_client_error("list_objects_v2", service_error_code="AccessDenied")
            with self.assertRaises(ClientError):
                cliente.list_objects_v2(Bucket=bucket)
            stub.add_response("list_objects_v2", {"Contents": []})
            self.assertEqual(cliente.list_objects_v2(Bucket=bucket), {"Contents": []})

    def test_configuracao_incompleta_e_rejeitada(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(PagamentosStorageErro):
                configuracao_bucket()

    def test_nome_remove_caminho_e_controles(self):
        self.assertEqual(limpar_nome_arquivo("../pasta/100,00\x00 hospedagem.pdf"), "100,00 hospedagem.pdf")

    def test_listagem_isola_prefixo_e_ignora_objeto_invalido(self):
        perfil = {"id": 7, "storage_prefix": "perfil_pagamentos/7"}
        with patch("routes.financeiro_novo.services.pagamentos_bucket._s3", return_value=(FakeS3(), "bucket")):
            arquivos = listar_arquivos(perfil, "novas_contas")
        self.assertEqual(len(arquivos), 1)
        self.assertEqual(arquivos[0]["id"], "a" * 32)
        self.assertEqual(arquivos[0]["name"], "100,00 hospedagem.pdf")

    def test_baixa_arquivo_para_replica_e_fecha_resposta(self):
        perfil = {"id": 7, "storage_prefix": "perfil_pagamentos/7"}
        s3 = FakeS3()
        with patch("routes.financeiro_novo.services.pagamentos_bucket._s3", return_value=(s3, "bucket")):
            arquivo = baixar_arquivo(perfil, "a" * 32)
        self.assertEqual(arquivo["conteudo"], b"%PDF-1.4\nrecibo")
        self.assertEqual(arquivo["mimeType"], "application/pdf")
        self.assertTrue(s3.corpo.closed)


class PortalIsolamentoTests(unittest.TestCase):
    def test_portal_nao_expoe_rotas_do_sistema_principal(self):
        with patch.dict(os.environ, {"SECRET_KEY": "teste-seguro"}, clear=False):
            from portal_arquivos import create_portal_app
            app = create_portal_app()
        regras = {regra.rule for regra in app.url_map.iter_rules()}
        self.assertIn("/p/<token>/<pasta>", regras)
        self.assertIn("/health", regras)
        self.assertNotIn("/dashboard", regras)
        self.assertNotIn("/auth/login", regras)

    def test_pagina_renderiza_sem_sessao_do_sistema(self):
        with patch.dict(os.environ, {"SECRET_KEY": "teste-seguro"}, clear=False):
            from portal_arquivos import create_portal_app
            app = create_portal_app()
        perfil = {
            "id": 7, "nome": "Administrativo", "matricula": "123",
            "portal_token": "t" * 40,
            "storage_prefix": "perfil_pagamentos/7",
        }
        with patch("portal_arquivos._perfil", return_value=perfil), \
             patch("portal_arquivos.listar_arquivos", return_value=[]):
            resposta = app.test_client().get("/p/" + "t" * 40 + "/novas_contas")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Arquivos de pagamentos", resposta.data)
        self.assertEqual(resposta.headers["X-Robots-Tag"], "noindex, nofollow, noarchive")


if __name__ == "__main__":
    unittest.main()
