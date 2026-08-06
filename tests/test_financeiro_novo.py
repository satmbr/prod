import io
import os
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from reportlab.pdfgen import canvas
from werkzeug.datastructures import FileStorage

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import create_app
from routes.financeiro_novo.services.anexos import (
    AnexoInvalido,
    nome_objeto_pdf,
    normalizar_anexo,
)
from routes.financeiro_novo.cadastros import TIPOS, _normalizar
from routes.financeiro_novo.services.valores import ValorInvalido, decimal_br
from routes.financeiro_novo.homologacao import diagnosticar_armazenamento


class FinanceiroNovoIsolamentoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raiz = Path(__file__).resolve().parents[1]

    def test_fundacao_nao_referencia_tabelas_do_financeiro_anterior(self):
        arquivos = [
            *list((self.raiz / "migrations").glob("*_financeiro_novo_*.sql")),
            *list((self.raiz / "routes" / "financeiro_novo").rglob("*.py")),
            *list((self.raiz / "templates" / "financeiro_novo").rglob("*.html")),
        ]
        conteudo = "\n".join(item.read_text(encoding="utf-8") for item in arquivos)
        self.assertNotIn("financeiro2_", conteudo.lower())
        self.assertIn("financeiro3_", conteudo.lower())

    def test_permissao_do_financeiro_atual_nao_abre_o_novo(self):
        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro:visualizar"]
                sessao["ultimo_acesso"] = 9999999999
            resposta = client.get("/financeiro-novo/")
        self.assertEqual(resposta.status_code, 403)

    def test_permissao_propria_abre_dashboard_sem_dados_antigos(self):
        resultado_config = MagicMock()
        resultado_config.mappings.return_value.one.return_value = {
            "nome_modulo": "Financeiro Novo",
            "ambiente": "HOMOLOGACAO",
            "versao_schema": 1,
        }
        resultado_totais = MagicMock()
        resultado_totais.mappings.return_value.one.return_value = {
            "despesas": 0,
            "missoes": 0,
            "acertos_pendentes": 0,
            "notas_debito": 0,
            "reembolsos": 0,
            "conciliacoes": 0,
            "cadastros": 0,
            "arquivos": 0,
            "anexos": 0,
            "eventos_auditoria": 0,
        }
        conexao = MagicMock()
        conexao.execute.side_effect = [resultado_config, resultado_totais]
        contexto = MagicMock()
        contexto.__enter__.return_value = conexao
        engine = MagicMock()
        engine.connect.return_value = contexto

        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with patch("routes.financeiro_novo.views.get_engine", return_value=engine):
            with app.test_client() as client:
                with client.session_transaction() as sessao:
                    sessao["usuario_id"] = 1
                    sessao["permissoes"] = ["financeiro_novo:visualizar"]
                    sessao["ultimo_acesso"] = 9999999999
                resposta = client.get("/financeiro-novo/")

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Base independente e vazia", resposta.get_data(as_text=True))
        sql_executado = " ".join(str(chamada.args[0]) for chamada in conexao.execute.call_args_list)
        self.assertNotIn("financeiro2_", sql_executado.lower())

    def test_cadastros_exigem_permissoes_proprias_para_escrita(self):
        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro_novo:visualizar"]
                sessao["ultimo_acesso"] = 9999999999
            resposta = client.post(
                "/financeiro-novo/cadastros/moedas/novo",
                data={"codigo": "BRL", "nome": "Real", "simbolo": "R$", "casas_decimais": "2"},
            )
        self.assertEqual(resposta.status_code, 403)

    def test_migration_cria_tabelas_relacionais_sem_exclusao_fisica(self):
        migration = (self.raiz / "migrations" / "004_financeiro_novo_cadastros.sql").read_text(encoding="utf-8")
        for tabela in ("pessoas", "centros_custo", "categorias", "moedas", "contas"):
            self.assertIn(f"financeiro3_{tabela}", migration)
        cadastros = (self.raiz / "routes" / "financeiro_novo" / "cadastros.py").read_text(encoding="utf-8")
        self.assertNotIn("DELETE FROM", cadastros.upper())

    def test_tela_de_cadastros_inicia_vazia_e_renderiza(self):
        resultado_registros = MagicMock()
        resultado_registros.mappings.return_value.all.return_value = []
        resultado_moedas = MagicMock()
        resultado_moedas.mappings.return_value.all.return_value = []
        conexao = MagicMock()
        conexao.execute.side_effect = [resultado_registros, resultado_moedas]
        contexto = MagicMock()
        contexto.__enter__.return_value = conexao
        engine = MagicMock()
        engine.connect.return_value = contexto

        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with patch("routes.financeiro_novo.cadastros.get_engine", return_value=engine):
            with app.test_client() as client:
                with client.session_transaction() as sessao:
                    sessao["usuario_id"] = 1
                    sessao["permissoes"] = ["financeiro_novo:visualizar"]
                    sessao["ultimo_acesso"] = 9999999999
                resposta = client.get("/financeiro-novo/cadastros?tipo=pessoas")

        self.assertEqual(resposta.status_code, 200)
        pagina = resposta.get_data(as_text=True)
        self.assertIn("Este cadastro começa vazio", pagina)
        self.assertNotIn("Novo cadastro", pagina)

    def test_despesas_usam_tabelas_novas_e_total_calculado_no_banco(self):
        migration = (self.raiz / "migrations" / "005_financeiro_novo_despesas.sql").read_text(encoding="utf-8")
        for tabela in ("despesas", "despesa_itens", "despesa_decisoes", "despesa_pagamentos"):
            self.assertIn(f"financeiro3_{tabela}", migration)
        self.assertIn("GENERATED ALWAYS AS", migration)
        self.assertIn("financeiro3_atualizar_total_despesa", migration)
        self.assertIn("NUMERIC(18, 2)", migration)
        self.assertNotIn("FLOAT", migration.upper())

    def test_permissao_de_edicao_nao_autoriza_aprovar_ou_pagar(self):
        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro_novo:visualizar", "financeiro_novo:editar"]
                sessao["ultimo_acesso"] = 9999999999
            aprovacao = client.post("/financeiro-novo/despesas/1/aprovar")
            pagamento = client.post("/financeiro-novo/despesas/1/pagar")
        self.assertEqual(aprovacao.status_code, 403)
        self.assertEqual(pagamento.status_code, 403)

    def test_om_rd_e_acertos_tem_modelo_independente_e_total_derivado(self):
        migration = (self.raiz / "migrations" / "006_financeiro_novo_om_rd.sql").read_text(encoding="utf-8")
        for tabela in ("oms", "om_decisoes", "rds", "rd_itens", "rd_decisoes", "rd_acertos"):
            self.assertIn(f"financeiro3_{tabela}", migration)
        self.assertIn("om_id BIGINT NOT NULL UNIQUE", migration)
        self.assertIn("financeiro3_atualizar_total_rd", migration)
        self.assertIn("'REEMBOLSO','DEVOLUCAO'", migration)

    def test_edicao_nao_autoriza_decidir_om_ou_rd(self):
        app = create_app()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro_novo:visualizar", "financeiro_novo:editar"]
                sessao["ultimo_acesso"] = 9999999999
            respostas = (
                client.post("/financeiro-novo/oms/1/aprovar"),
                client.post("/financeiro-novo/rds/1/aprovar"),
                client.post("/financeiro-novo/rds/1/liquidar"),
            )
        self.assertTrue(all(resposta.status_code == 403 for resposta in respostas))

    def test_notas_relatorios_e_conciliacao_usam_modelo_novo(self):
        migration = (self.raiz / "migrations" / "007_financeiro_novo_nd_relatorios.sql").read_text(encoding="utf-8")
        for tabela in ("clientes", "notas_debito", "nd_itens", "nd_decisoes", "nd_recebimentos", "conciliacoes"):
            self.assertIn(f"financeiro3_{tabela}", migration)
        self.assertIn("financeiro3_atualizar_total_nd", migration)
        self.assertIn("UNIQUE (origem_tipo,origem_id)", migration)

    def test_reembolsos_e_previsao_usam_apenas_modelo_novo(self):
        migration = (self.raiz / "migrations" / "008_financeiro_novo_reembolsos_previsao.sql").read_text(encoding="utf-8")
        for tabela in ("reembolsos", "reembolso_itens", "reembolso_decisoes", "reembolso_pagamentos"):
            self.assertIn(f"financeiro3_{tabela}", migration)
        self.assertIn("financeiro3_atualizar_total_reembolso", migration)
        self.assertNotIn("FLOAT", migration.upper())
        previsao = (self.raiz / "routes" / "financeiro_novo" / "previsao.py").read_text(encoding="utf-8")
        for origem in ("financeiro3_despesas", "financeiro3_reembolsos", "financeiro3_rd_acertos", "financeiro3_notas_debito"):
            self.assertIn(origem, previsao)
        relatorios = (self.raiz / "routes" / "financeiro_novo" / "relatorios.py").read_text(encoding="utf-8")
        self.assertIn("PAGAMENTO_REEMBOLSO", relatorios)
        self.assertNotIn("ADIANTAMENTO_OM", relatorios)

    def test_om_tem_numero_matricula_linhas_e_total_derivado(self):
        migration = (self.raiz / "migrations" / "009_financeiro_novo_om_linhas.sql").read_text(encoding="utf-8")
        for campo in ("numero_om", "matricula_favorecido", "valor_total"):
            self.assertIn(campo, migration)
        self.assertIn("financeiro3_om_itens", migration)
        self.assertIn("financeiro3_atualizar_total_om", migration)
        self.assertIn("removido_em", migration)
        self.assertNotIn("FLOAT", migration.upper())

    def test_formulario_om_nao_exibe_campos_descontinuados(self):
        campos = (self.raiz / "templates" / "financeiro_novo" / "_om_campos.html").read_text(encoding="utf-8")
        self.assertIn('name="numero_om"', campos)
        self.assertIn('name="matricula_favorecido"', campos)
        for nome in ("objetivo", "valor_adiantamento", "origem", "destino", "data_inicio", "data_fim"):
            self.assertNotIn(f'name="{nome}"', campos)
        detalhe = (self.raiz / "templates" / "financeiro_novo" / "om_detalhe.html").read_text(encoding="utf-8")
        self.assertIn("om_item_novo", detalhe)
        self.assertIn("justificativa_sem_comprovante", detalhe)

    def test_reembolso_separa_edicao_aprovacao_e_pagamento(self):
        app = create_app(); app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro_novo:visualizar", "financeiro_novo:editar"]
                sessao["ultimo_acesso"] = 9999999999
            aprovacao = client.post("/financeiro-novo/reembolsos/1/aprovar")
            pagamento = client.post("/financeiro-novo/reembolsos/1/pagar")
        self.assertEqual(aprovacao.status_code, 403)
        self.assertEqual(pagamento.status_code, 403)

    def test_conciliacao_exige_permissao_administrativa_do_modulo(self):
        app = create_app(); app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro_novo:visualizar", "financeiro_novo:editar"]
                sessao["ultimo_acesso"] = 9999999999
            resposta = client.get("/financeiro-novo/conciliacao")
        self.assertEqual(resposta.status_code, 403)

    def test_homologacao_exige_permissao_administrativa_do_modulo(self):
        app = create_app(); app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.test_client() as client:
            with client.session_transaction() as sessao:
                sessao["usuario_id"] = 1
                sessao["permissoes"] = ["financeiro_novo:visualizar"]
                sessao["ultimo_acesso"] = 9999999999
            resposta = client.get("/financeiro-novo/homologacao")
        self.assertEqual(resposta.status_code, 403)

    def test_diagnostico_de_armazenamento_nao_cria_diretorios(self):
        app = create_app(); app.config.update(TESTING=True, UPLOAD_ROOT=str(self.raiz / "diretorio-que-nao-existe"))
        with app.app_context():
            diagnostico = diagnosticar_armazenamento()
        self.assertFalse(diagnostico["existe"])
        self.assertFalse((self.raiz / "diretorio-que-nao-existe").exists())


class FinanceiroNovoCadastrosTests(unittest.TestCase):
    def test_pessoa_exige_papel_e_normaliza_documento(self):
        dados, erros = _normalizar(
            TIPOS["pessoas"],
            {
                "tipo_pessoa": "JURIDICA",
                "nome_razao": "Fornecedor Teste",
                "documento": "12.345.678/0001-90",
                "fornecedor": "on",
            },
        )
        self.assertEqual(erros, [])
        self.assertEqual(dados["documento"], "12345678000190")
        self.assertTrue(dados["fornecedor"])

        _, erros_sem_papel = _normalizar(
            TIPOS["pessoas"],
            {"tipo_pessoa": "FISICA", "nome_razao": "Favorecido"},
        )
        self.assertTrue(any("fornecedor" in erro.lower() for erro in erros_sem_papel))

    def test_moeda_exige_codigo_iso_de_tres_letras(self):
        dados, erros = _normalizar(
            TIPOS["moedas"],
            {"codigo": "br", "nome": "Real", "simbolo": "R$", "casas_decimais": "2"},
        )
        self.assertEqual(dados["codigo"], "BR")
        self.assertTrue(any("3 letras" in erro for erro in erros))

    def test_tipo_de_conta_fora_da_lista_e_rejeitado(self):
        _, erros = _normalizar(
            TIPOS["contas"],
            {"nome": "Conta", "tipo": "CRIPTO", "moeda_id": "1"},
        )
        self.assertTrue(any("Tipo é inválido" in erro for erro in erros))


class FinanceiroNovoValoresTests(unittest.TestCase):
    def test_decimal_aceita_formato_brasileiro_sem_usar_float(self):
        self.assertEqual(decimal_br("1.234,56"), Decimal("1234.56"))
        self.assertEqual(decimal_br("10,999", casas=2), Decimal("11.00"))

    def test_decimal_bloqueia_zero_em_pagamentos_e_itens(self):
        with self.assertRaises(ValorInvalido):
            decimal_br("0,00", positivo=True)


class FinanceiroNovoAnexosTests(unittest.TestCase):
    def test_foto_e_convertida_para_pdf_canonico(self):
        origem = io.BytesIO()
        Image.new("RGB", (1600, 1000), "white").save(origem, format="BMP")
        origem.seek(0)
        arquivo = FileStorage(stream=origem, filename="recibo.bmp", content_type="image/bmp")

        anexo = normalizar_anexo(arquivo)

        self.assertTrue(anexo.conteudo.startswith(b"%PDF-"))
        self.assertEqual(anexo.mime_canonico, "application/pdf")
        self.assertEqual(anexo.paginas, 1)
        self.assertEqual(len(anexo.sha256_canonico), 64)
        self.assertLess(anexo.tamanho_canonico, anexo.tamanho_original)

    def test_nome_do_objeto_usa_pdf_em_diretorio_exclusivo(self):
        nome = nome_objeto_pdf("abcdef12-3456-7890-abcd-ef1234567890")
        self.assertEqual(
            nome,
            "financeiro_novo/ab/abcdef12-3456-7890-abcd-ef1234567890.pdf",
        )

    def test_pdf_e_regravado_e_validado(self):
        origem = io.BytesIO()
        documento = canvas.Canvas(origem)
        documento.drawString(50, 800, "Recibo de teste")
        documento.save()
        origem.seek(0)
        arquivo = FileStorage(stream=origem, filename="recibo.pdf", content_type="application/pdf")

        anexo = normalizar_anexo(arquivo)

        self.assertTrue(anexo.conteudo.startswith(b"%PDF-"))
        self.assertEqual(anexo.paginas, 1)

    def test_arquivo_que_nao_e_foto_nem_pdf_e_rejeitado(self):
        arquivo = FileStorage(
            stream=io.BytesIO(b"conteudo executavel"),
            filename="recibo.exe",
            content_type="application/octet-stream",
        )
        with self.assertRaises(AnexoInvalido):
            normalizar_anexo(arquivo)


if __name__ == "__main__":
    unittest.main()
