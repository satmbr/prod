import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class BotPrumatEstruturaTests(unittest.TestCase):
    def test_migracao_separa_identidade_web_e_telegram(self):
        sql = (ROOT / "migrations" / "025_bot_prumat_fluxos.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS bot_colaboradores", sql)
        self.assertIn("colaborador_id INTEGER NOT NULL UNIQUE", sql)
        self.assertIn("usuario_id INTEGER UNIQUE", sql)
        self.assertIn("telegram_chat_id BIGINT UNIQUE", sql)

    def test_migracao_suporta_multiplos_aprovadores_e_primeira_decisao(self):
        sql = (ROOT / "migrations" / "025_bot_prumat_fluxos.sql").read_text(encoding="utf-8")
        self.assertIn("bot_fluxo_aprovadores", sql)
        self.assertIn("QUALQUER_UM", sql)
        self.assertIn("bot_solicitacao_aprovacoes", sql)
        self.assertIn("bot_solicitacao_eventos", sql)

    def test_quatro_fluxos_iniciais_sao_criados(self):
        sql = (ROOT / "migrations" / "025_bot_prumat_fluxos.sql").read_text(encoding="utf-8")
        for codigo in ("PASSAGEM", "MATERIAL", "EPI", "REEMBOLSO"):
            self.assertIn(f"('{codigo}'", sql)

    def test_telegram_preserva_fluxo_financeiro_como_fallback(self):
        fonte = (ROOT / "telegram_bot.py").read_text(encoding="utf-8")
        self.assertIn("if not processar_update_bot(update):", fonte)
        self.assertIn("processar_update(update)", fonte)

    def test_rotas_do_modulo_estao_registradas(self):
        os.environ.setdefault("SECRET_KEY", "teste")
        from app import app
        regras = {regra.rule for regra in app.url_map.iter_rules()}
        self.assertIn("/bot", regras)
        self.assertIn("/bot/colaboradores", regras)
        self.assertIn("/bot/fluxos", regras)
        self.assertIn("/bot/solicitacoes", regras)


class BotPrumatDispatchTests(unittest.TestCase):
    def test_mensagem_financeira_continua_no_processador_antigo(self):
        import telegram_bot
        app = telegram_bot.create_telegram_app()
        app.testing = True
        update = {"update_id": 1, "message": {"chat": {"id": 2}, "document": {"file_id": "x"}}}
        with patch.object(telegram_bot, "webhook_autentico", return_value=True), \
             patch.object(telegram_bot, "processar_update_bot", return_value=False) as novo, \
             patch.object(telegram_bot, "processar_update") as antigo:
            resposta = app.test_client().post("/telegram/webhook", json=update)
        self.assertEqual(resposta.status_code, 200)
        novo.assert_called_once_with(update)
        antigo.assert_called_once_with(update)

    def test_mensagem_corporativa_nao_e_duplicada_no_financeiro(self):
        import telegram_bot
        app = telegram_bot.create_telegram_app()
        app.testing = True
        update = {"update_id": 1, "message": {"chat": {"id": 2}, "text": "/menu"}}
        with patch.object(telegram_bot, "webhook_autentico", return_value=True), \
             patch.object(telegram_bot, "processar_update_bot", return_value=True), \
             patch.object(telegram_bot, "processar_update") as antigo:
            resposta = app.test_client().post("/telegram/webhook", json=update)
        self.assertEqual(resposta.status_code, 200)
        antigo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
