import base64
import json
import os
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from routes.financeiro_novo.services.pagamentos_drive import (
    NomeContaInvalido,
    conta_pronta_para_quitadas,
    email_conta_servico,
    extrair_id_pasta,
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

    def test_extrai_id_de_link_ou_id_direto(self):
        folder_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
        self.assertEqual(extrair_id_pasta(f"https://drive.google.com/drive/folders/{folder_id}?usp=sharing"), folder_id)
        self.assertEqual(extrair_id_pasta(folder_id), folder_id)


class PerfilPagamentosConfiguracaoTests(unittest.TestCase):
    def test_email_da_conta_de_servico_em_json_ou_base64(self):
        info = {"client_email": "robot@projeto.iam.gserviceaccount.com"}
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(info)}, clear=False):
            self.assertEqual(email_conta_servico(), info["client_email"])
        encoded = base64.b64encode(json.dumps(info).encode()).decode()
        with patch.dict(os.environ, {"GOOGLE_SERVICE_ACCOUNT_JSON": encoded}, clear=False):
            self.assertEqual(email_conta_servico(), info["client_email"])

    def test_migration_e_rotas_mantem_modulo_independente(self):
        migration = (ROOT / "migrations" / "014_perfil_pagamentos_drive.sql").read_text(encoding="utf-8")
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_drive.py").read_text(encoding="utf-8")
        self.assertIn("'perfil_pagamentos'", migration)
        self.assertIn("financeiro3_pagamento_perfis", migration)
        self.assertIn("financeiro3_pagamento_contas", migration)
        self.assertIn("financeiro3_pagamento_comprovantes", migration)
        self.assertNotIn("financeiro3_oms", migration + routes + service)

    def test_painel_tem_sincronizacao_manual_de_todos_os_perfis(self):
        routes = (ROOT / "routes" / "financeiro_novo" / "perfil_pagamentos.py").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "financeiro_novo" / "pagamentos_painel.html").read_text(encoding="utf-8")
        self.assertIn('@bp.post("/perfil-pagamentos/sincronizar")', routes)
        self.assertIn("financeiro_novo.pagamentos_sincronizar", template)
        self.assertIn("Sincronizar tudo agora", template)

    def test_importacao_nao_reutiliza_status_em_case_do_postgresql(self):
        service = (ROOT / "routes" / "financeiro_novo" / "services" / "pagamentos_drive.py").read_text(encoding="utf-8")
        self.assertNotIn("CASE WHEN :pagamento", service)
        self.assertNotIn("CASE WHEN :reembolso", service)
        self.assertIn('"data_pagamento": date.today()', service)
        self.assertIn('"status_sincronizacao": (', service)


if __name__ == "__main__":
    unittest.main()
