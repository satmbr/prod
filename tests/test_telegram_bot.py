import os
import unittest
from unittest.mock import patch

import telegram_bot
from routes.financeiro_novo.services import pagamentos_telegram


class TelegramBotHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = telegram_bot.create_telegram_app().test_client()

    def test_health_identifica_servico_isolado(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["service"], "telegram-bot")
        self.assertEqual(self.client.get("/").status_code, 404)

    def test_webhook_rejeita_cabecalho_invalido(self):
        with patch.object(telegram_bot, "webhook_autentico", return_value=False):
            response = self.client.post("/telegram/webhook", json={"update_id": 1})
        self.assertEqual(response.status_code, 403)

    def test_webhook_processa_json_autenticado(self):
        update = {"update_id": 1, "message": {"chat": {"id": 2}}}
        with (
            patch.object(telegram_bot, "webhook_autentico", return_value=True),
            patch.object(telegram_bot, "processar_update") as processar,
        ):
            response = self.client.post("/telegram/webhook", json=update)
        self.assertEqual(response.status_code, 200)
        processar.assert_called_once_with(update)


class TelegramBotArquivoTests(unittest.TestCase):
    def test_documento_preserva_nome_original(self):
        nome, file_id, tamanho, mime = pagamentos_telegram._nome_e_arquivo({
            "document": {
                "file_name": "254,00 hospedagem.pdf",
                "file_id": "telegram-file",
                "file_size": 123,
                "mime_type": "application/pdf",
            }
        })
        self.assertEqual(nome, "254,00 hospedagem.pdf")
        self.assertEqual((file_id, tamanho, mime), ("telegram-file", 123, "application/pdf"))

    def test_foto_usa_legenda_como_nome(self):
        nome, file_id, _, mime = pagamentos_telegram._nome_e_arquivo({
            "caption": "254,00 hospedagem",
            "photo": [{"file_id": "menor"}, {"file_id": "maior", "file_size": 456}],
        })
        self.assertEqual(nome, "254,00 hospedagem.jpg")
        self.assertEqual(file_id, "maior")
        self.assertEqual(mime, "image/jpeg")

    def test_foto_sem_legenda_e_rejeitada(self):
        with self.assertRaises(pagamentos_telegram.TelegramErro):
            pagamentos_telegram._nome_e_arquivo({"photo": [{"file_id": "foto"}]})

    def test_segredo_do_webhook_usa_comparacao_exata(self):
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "segredo_123"}, clear=False):
            self.assertTrue(pagamentos_telegram.webhook_autentico("segredo_123"))
            self.assertFalse(pagamentos_telegram.webhook_autentico("segredo"))


if __name__ == "__main__":
    unittest.main()
