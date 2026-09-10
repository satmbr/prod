import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from routes.financeiro_novo.services.pagamentos_nomes import (
    NomeContaInvalido,
    conta_pronta_para_quitadas,
    formatar_valor_nome,
    interpretar_nome_conta,
    nome_controlado,
    numero_conta_do_comprovante,
)


ROOT = Path(__file__).resolve().parents[1]


class PerfilPagamentosNomeTests(unittest.TestCase):
    def test_nome_simples_com_descricao_de_varias_palavras(self):
        conta = interpretar_nome_conta(
            "100,50 25.09.2026 28.09.2026 manutencao veicular ABERTA PENDENTE.pdf"
        )
        self.assertEqual(conta.valor, Decimal("100.50"))
        self.assertEqual(conta.data_documento, date(2026, 9, 25))
        self.assertEqual(conta.data_vencimento, date(2026, 9, 28))
        self.assertEqual(conta.descricao, "manutencao veicular")
        self.assertEqual(conta.status_pagamento, "ABERTA")
        self.assertEqual(conta.status_reembolso, "PENDENTE")

    def test_nome_ja_numerado_pode_ser_interpretado(self):
        conta = interpretar_nome_conta(
            "CP-000123 1.234,56 01.09.2026 30.09.2026 locacao equipamento PAGA REEMBOLSADA.JPG"
        )
        self.assertEqual(conta.valor, Decimal("1234.56"))
        self.assertEqual(conta.extensao, ".jpg")

    def test_vencimento_anterior_ao_documento_e_rejeitado(self):
        with self.assertRaises(NomeContaInvalido):
            interpretar_nome_conta(
                "100,50 28.09.2026 25.09.2026 manutencao ABERTA PENDENTE.pdf"
            )

    def test_so_valor_e_descricao_usam_data_e_status_padrao(self):
        conta = interpretar_nome_conta("254,00 hospedagem.jpeg")
        self.assertEqual(conta.valor, Decimal("254.00"))
        self.assertEqual(conta.data_documento, date.today())
        self.assertEqual(conta.data_vencimento, date.today())
        self.assertEqual(conta.descricao, "hospedagem")
        self.assertEqual(conta.status_pagamento, "ABERTA")
        self.assertEqual(conta.status_reembolso, "PENDENTE")

    def test_uma_data_define_documento_e_vencimento_atual(self):
        conta = interpretar_nome_conta("254,00 01.09.2026 abastecimento.jpeg")
        self.assertEqual(conta.data_documento, date(2026, 9, 1))
        self.assertEqual(conta.data_vencimento, date.today())
        self.assertEqual(conta.descricao, "abastecimento")
        self.assertEqual(conta.status_pagamento, "ABERTA")
        self.assertEqual(conta.status_reembolso, "PENDENTE")

    def test_descricao_continua_obrigatoria(self):
        with self.assertRaises(NomeContaInvalido):
            interpretar_nome_conta("254,00.pdf")

    def test_nome_controlado_preserva_numero_datas_e_status(self):
        nome = nome_controlado({
            "numero": "CP-000001",
            "valor": Decimal("1234.50"),
            "data_documento": date(2026, 9, 25),
            "data_vencimento": date(2026, 9, 28),
            "descricao": "manutencao veicular",
            "status_pagamento": "PAGA",
            "status_reembolso": "PENDENTE",
            "drive_nome_atual": "original.pdf",
        })
        self.assertEqual(
            nome,
            "CP-000001 1.234,50 25.09.2026 28.09.2026 manutencao veicular PAGA PENDENTE.pdf",
        )
        self.assertEqual(formatar_valor_nome(Decimal("10.5")), "10,50")

    def test_comprovante_aceita_numero_sozinho_ou_com_sufixo(self):
        self.assertEqual(numero_conta_do_comprovante("CP-000001.pdf"), "CP-000001")
        self.assertEqual(numero_conta_do_comprovante("cp-000001 02.jpg"), "CP-000001")
        self.assertEqual(numero_conta_do_comprovante("CP-000001__frente.png"), "CP-000001")
        self.assertIsNone(numero_conta_do_comprovante("comprovante.pdf"))

    def test_quitada_exige_pagamento_reembolso_e_numero_om(self):
        base = {"status_pagamento": "PAGA", "status_reembolso": "REEMBOLSADA", "numero_om": None}
        self.assertFalse(conta_pronta_para_quitadas(base))
        base["numero_om"] = "OM 9988"
        self.assertTrue(conta_pronta_para_quitadas(base))

class PerfilPagamentosConfiguracaoTests(unittest.TestCase):
    def test_migration_e_rotas_mantem_modulo_independente(self):
        migration = (ROOT / "migrations" / "014_perfil_pagamentos_drive.sql").read_text(encoding="utf-8")
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_bucket.py").read_text(encoding="utf-8")
        self.assertIn("'perfil_pagamentos'", migration)
        self.assertIn("financeiro3_pagamento_perfis", migration)
        self.assertIn("financeiro3_pagamento_contas", migration)
        self.assertIn("financeiro3_pagamento_comprovantes", migration)
        self.assertNotIn("financeiro3_oms", migration + service)

    def test_conta_pode_ser_replicada_para_om_em_rascunho(self):
        migration = (ROOT / "migrations" / "020_perfil_pagamentos_replica_om.sql").read_text(encoding="utf-8")
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        painel = (ROOT / "templates" / "financeiro_novo" / "pagamentos_painel.html").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS om_id", migration)
        self.assertIn("ADD COLUMN IF NOT EXISTS om_item_id", migration)
        self.assertIn("A_CLASSIFICAR", migration)
        self.assertIn('@bp.post("/perfil-pagamentos/contas/<int:conta_id>/replicar-om")', routes)
        self.assertIn("o.status='RASCUNHO'", routes)
        self.assertIn("CRIADO_PELO_PERFIL_PAGAMENTOS", routes)
        self.assertIn('@bp.get("/perfil-pagamentos/contas/<int:conta_id>/duplicidades-om")', routes)
        self.assertIn("FROM financeiro3_om_itens", routes)
        self.assertNotIn("financeiro3_rd_itens", routes)
        self.assertIn("confirmar_duplicidade", painel)
        self.assertIn("Possíveis lançamentos repetidos em OMs", painel)
        self.assertIn("pp-replicate", painel)
        self.assertIn("Replicar linha", painel)

    def test_conta_pode_ser_desvinculada_da_om_com_remocao_condicional(self):
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        painel = (ROOT / "templates" / "financeiro_novo" / "pagamentos_painel.html").read_text(encoding="utf-8")
        self.assertIn('@bp.post("/perfil-pagamentos/contas/<int:conta_id>/desvincular-om")', routes)
        self.assertIn('om["status"] == "RASCUNHO"', routes)
        self.assertIn("REMOVIDO_POR_DESVINCULO_PERFIL_PAGAMENTOS", routes)
        self.assertIn("SET om_id=NULL,om_item_id=NULL", routes)
        self.assertIn("pp-om-actions-open", painel)
        self.assertIn("Abrir OM", painel)
        self.assertIn("Desvincular", painel)
        self.assertIn("Confirma o desvínculo", painel)

    def test_linha_de_om_pode_ser_editada_depois_da_replica(self):
        routes = (ROOT / "routes" / "financeiro_novo" / "missoes.py").read_text(encoding="utf-8")
        detalhe = (ROOT / "templates" / "financeiro_novo" / "om_detalhe.html").read_text(encoding="utf-8")
        self.assertIn('@bp.post("/oms/<int:om_id>/itens/<int:item_id>/editar")', routes)
        self.assertIn("om_item_editar", detalhe)

    def test_painel_tem_sincronizacao_manual_de_todos_os_perfis(self):
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "financeiro_novo" / "pagamentos_painel.html").read_text(encoding="utf-8")
        self.assertIn('@bp.post("/perfil-pagamentos/sincronizar")', routes)
        self.assertIn("financeiro_novo.pagamentos_sincronizar", template)
        self.assertIn("Sincronizar tudo agora", template)

    def test_importacao_nao_reutiliza_status_em_case_do_postgresql(self):
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_bucket.py").read_text(encoding="utf-8")
        self.assertNotIn("CASE WHEN :pagamento", service)
        self.assertNotIn("CASE WHEN :reembolso", service)
        self.assertIn('"data_pagamento": date.today()', service)
        self.assertIn('"sync": "AGUARDANDO_OM"', service)

    def test_interface_e_migracao_removem_email_do_perfil(self):
        form = (ROOT / "templates" / "financeiro_novo" / "pagamento_perfil_form.html").read_text(encoding="utf-8")
        painel = (ROOT / "templates" / "financeiro_novo" / "pagamentos_painel.html").read_text(encoding="utf-8")
        migration = (ROOT / "migrations" / "016_perfil_pagamentos_sem_email.sql").read_text(encoding="utf-8")
        self.assertNotIn('name="gmail"', form)
        self.assertNotIn("perfil.gmail", painel)
        self.assertIn("SET gmail=NULL", migration)

    def test_telegram_tem_vinculo_por_perfil_e_servico_isolado(self):
        migration = (ROOT / "migrations" / "017_perfil_pagamentos_telegram.sql").read_text(encoding="utf-8")
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        painel = (ROOT / "templates" / "financeiro_novo" / "pagamentos_painel.html").read_text(encoding="utf-8")
        bot = (ROOT / "telegram_bot.py").read_text(encoding="utf-8")
        self.assertIn("telegram_token", migration)
        self.assertIn("financeiro3_pagamento_telegram_updates", migration)
        self.assertIn("pagamento_perfil_regenerar_telegram", routes)
        self.assertIn("Vincular Telegram", painel)
        self.assertNotIn("register_blueprint", bot)

    def test_perfil_aceita_multiplos_chats_do_telegram(self):
        migration = (ROOT / "migrations" / "021_perfil_pagamentos_multiplos_telegrams.sql").read_text(encoding="utf-8")
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_telegram.py").read_text(encoding="utf-8")
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        form = (ROOT / "templates" / "financeiro_novo" / "pagamento_perfil_form.html").read_text(encoding="utf-8")
        self.assertIn("financeiro3_pagamento_telegram_chats", migration)
        self.assertIn("ON CONFLICT (chat_id) DO UPDATE", migration)
        self.assertIn("FROM financeiro3_pagamento_telegram_chats", service)
        self.assertIn("INSERT INTO financeiro3_pagamento_telegram_chats", service)
        self.assertNotIn("Este perfil já está vinculado a outro chat", service)
        self.assertIn("pagamento_perfil_telegram_remover", routes)
        self.assertIn("chats_preservados", routes)
        self.assertIn("Vincular outro Telegram", form)
        self.assertIn("Telegrams autorizados", form)

    def test_telegram_persiste_cadastro_guiado_sem_guardar_arquivo(self):
        migration = (ROOT / "migrations" / "018_telegram_cadastro_guiado.sql").read_text(encoding="utf-8")
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_telegram.py").read_text(encoding="utf-8")
        self.assertIn("financeiro3_pagamento_telegram_pendencias", migration)
        self.assertIn("update_id_arquivo", migration)
        self.assertNotIn("BYTEA", migration.upper())
        self.assertIn('elif comando == "/cancelar"', service)
        self.assertIn('"max_connections": 1', service)

    def test_telegram_confere_duplicidade_somente_em_oms_e_envia_recibo(self):
        migration = (ROOT / "migrations" / "022_telegram_duplicidade_om.sql").read_text(encoding="utf-8")
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_telegram.py").read_text(encoding="utf-8")
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("CONFIRMAR_DUPLICIDADE", migration)
        self.assertIn("financeiro3_pagamento_telegram_recibo_tokens", migration)
        self.assertIn("FROM financeiro3_om_itens i", service)
        self.assertIn("i.data_despesa=:data AND i.valor=:valor", service)
        self.assertNotIn("financeiro3_rd_itens", service)
        self.assertIn('enviar_documento_url(chat_id, url, legenda)', service)
        self.assertIn("ENVIAR MESMO ASSIM", service)
        self.assertIn("CANCELAR ENVIO", service)
        self.assertIn("pagamento_telegram_recibo_temporario", routes)
        self.assertIn("t.expira_em>NOW()", routes)
        self.assertIn('"financeiro_novo.pagamento_telegram_recibo_temporario"', app)


if __name__ == "__main__":
    unittest.main()
