import os
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret-key")
from app import create_app
from routes.financeiro_novo.missoes import _consultar_recibos


class ConsultaRecibosSQLTests(unittest.TestCase):
    def test_busca_exata_em_om_rd_e_anexos_ativos_sem_duplicar_lancamentos(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE financeiro3_pessoas(id INTEGER, nome_razao TEXT);
            CREATE TABLE financeiro3_moedas(id INTEGER, codigo TEXT);
            CREATE TABLE financeiro3_oms(id INTEGER, numero_om TEXT, status TEXT,
              solicitante_id INTEGER, moeda_id INTEGER, removido_em TEXT);
            CREATE TABLE financeiro3_rds(id INTEGER, numero_rd TEXT, status TEXT,
              responsavel_id INTEGER, moeda_id INTEGER);
            CREATE TABLE financeiro3_om_itens(id INTEGER, om_id INTEGER,
              data_despesa TEXT, descricao TEXT, valor NUMERIC, status TEXT);
            CREATE TABLE financeiro3_rd_itens(id INTEGER, rd_id INTEGER,
              data_despesa TEXT, descricao TEXT, valor NUMERIC, status TEXT);
            CREATE TABLE financeiro3_anexos(entidade TEXT, entidade_id INTEGER,
              arquivo_id TEXT, status TEXT);
            CREATE TABLE financeiro3_arquivos(id TEXT, nome_original TEXT, status TEXT);
            INSERT INTO financeiro3_pessoas VALUES(1,'Maria');
            INSERT INTO financeiro3_moedas VALUES(1,'BRL');
            INSERT INTO financeiro3_oms VALUES(1,'OM-001','APROVADA',1,1,NULL);
            INSERT INTO financeiro3_oms VALUES(2,'REMOVIDA','RASCUNHO',1,1,'2026-10-01');
            INSERT INTO financeiro3_rds VALUES(1,'RD-001','LIQUIDADA',1,1);
            INSERT INTO financeiro3_om_itens VALUES
              (1,1,'2026-10-28','OM correta',1234.56,'ATIVO'),
              (2,1,'2026-10-27','Outra data',1234.56,'ATIVO'),
              (3,1,'2026-10-28','Outro valor',1234.57,'ATIVO'),
              (4,1,'2026-10-28','Item removido',1234.56,'REMOVIDO'),
              (5,2,'2026-10-28','OM removida',1234.56,'ATIVO'),
              (6,1,'2026-10-28','Sem anexo',1234.56,'ATIVO');
            INSERT INTO financeiro3_rd_itens VALUES
              (1,1,'2026-10-28','RD correta',1234.56,'ATIVO'),
              (2,1,'2026-10-27','Outra data RD',1234.56,'ATIVO'),
              (3,1,'2026-10-28','Outro valor RD',1234.55,'ATIVO'),
              (4,1,'2026-10-28','RD item removido',1234.56,'REMOVIDO');
            INSERT INTO financeiro3_arquivos VALUES
              ('a','recibo.pdf','ATIVO'),('b','rd-1.pdf','ATIVO'),
              ('c','rd-2.pdf','ATIVO'),('d','inativo.pdf','REMOVIDO');
            INSERT INTO financeiro3_anexos VALUES
              ('OM_ITEM',1,'a','ATIVO'),('OM_ITEM',1,'a','ATIVO'),
              ('OM_ITEM',1,'b','REMOVIDO'),('OM_ITEM',1,'d','ATIVO'),
              ('RD',1,'b','ATIVO'),('RD',1,'c','ATIVO'),
              ('RD',1,'d','ATIVO'),('RD_PAGAMENTO',1,'a','ATIVO');
        """)
        conn = MagicMock()
        def execute(sql, params):
            rows = db.execute(str(sql), {k: str(v) for k, v in params.items()}).fetchall()
            result = MagicMock()
            result.mappings.return_value.all.return_value = [dict(r) for r in rows]
            return result
        conn.execute.side_effect = execute
        rows = _consultar_recibos(conn, date(2026,10,28), Decimal('1234.56'))
        self.assertEqual([r['descricao'] for r in rows], ['OM correta','Sem anexo','RD correta'])
        self.assertEqual([a['arquivo_id'] for a in rows[0]['anexos']], ['a'])
        self.assertEqual(rows[1]['anexos'], [])
        self.assertEqual([a['arquivo_id'] for a in rows[2]['anexos']], ['b','c'])
        self.assertEqual(_consultar_recibos(conn, date(2026,10,28), Decimal('99.99')), [])


class ConsultaRecibosHTTPTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s.update(usuario_id=1, permissoes=['financeiro_novo:visualizar'], ultimo_acesso=9999999999)
        self.engine = MagicMock()
        self.conn = self.engine.connect.return_value.__enter__.return_value
        self.conn.execute.return_value.mappings.return_value.all.return_value = []
        self.addCleanup(patch.stopall)
        patch('routes.financeiro_novo.missoes.get_engine', return_value=self.engine).start()

    def test_formulario_sem_busca_e_validacao_sem_consultar_recibos(self):
        with patch('routes.financeiro_novo.missoes._consultar_recibos') as consultar:
            response = self.client.get('/financeiro-novo/missoes')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Consultar recibo', response.get_data(as_text=True))
            for data, valor in [('','10'),('2026-02-30','10'),('2026-10-28',''),
                                ('2026-10-28','-10'),('2026-10-28','NaN'),('2026-10-28','1e999')]:
                response = self.client.get('/financeiro-novo/missoes', query_string={
                    'recibo_data':data, 'recibo_valor':valor})
                self.assertEqual(response.status_code, 200)
                self.assertIn('role="alert"', response.get_data(as_text=True))
            consultar.assert_not_called()

    def test_resultados_preservam_valor_br_e_links_de_conferencia(self):
        arquivo = '47d668e8-0877-4fde-8230-5c20a653d5a4'
        base = dict(documento_id=1, numero='001', documento_status='APROVADA',
                    responsavel='Maria', item_id=2, data_despesa=date(2026,10,28),
                    descricao='<script>teste</script>', valor=Decimal('1234.56'), moeda='BRL',
                    anexos=[dict(arquivo_id=arquivo,nome_original='recibo.pdf')])
        with patch('routes.financeiro_novo.missoes._consultar_recibos',
                   return_value=[dict(base,tipo='OM'),dict(base,tipo='RD')]) as consultar:
            response = self.client.get('/financeiro-novo/missoes?recibo_data=2026-10-28&recibo_valor=1.234,56')
            consultar.assert_called_once_with(self.conn,date(2026,10,28),Decimal('1234.56'))
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code,200)
        self.assertIn('2 lançamento(s)',html)
        self.assertIn(f'/oms/1/itens/2/anexos/{arquivo}?visualizar=1',html)
        self.assertIn(f'/documentos/rd/1/anexos/{arquivo}?visualizar=1',html)
        self.assertIn('Anexos da RD',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>teste</script>',html)

    def test_sem_resultados(self):
        with patch('routes.financeiro_novo.missoes._consultar_recibos',return_value=[]):
            r = self.client.get('/financeiro-novo/missoes?recibo_data=2026-10-28&recibo_valor=12,34')
        self.assertIn('Nenhum lançamento encontrado em OM ou RD',r.get_data(as_text=True))

    def test_exige_permissao_de_visualizacao(self):
        with self.client.session_transaction() as s:
            s['permissoes'] = ['financeiro:visualizar']
        self.assertEqual(self.client.get('/financeiro-novo/missoes').status_code,403)
        self.engine.connect.assert_not_called()

    def test_visualizacao_inline_e_download_padrao_om_rd(self):
        arquivo = '47d668e8-0877-4fde-8230-5c20a653d5a4'
        self.conn.execute.return_value.mappings.return_value.first.return_value = {
            'object_key':'recibo.pdf','nome_original':'recibo.pdf'}
        with tempfile.TemporaryDirectory() as raiz:
            Path(raiz,'recibo.pdf').write_bytes(b'%PDF-1.4 teste')
            self.app.config['UPLOAD_ROOT'] = raiz
            for rota in [f'/financeiro-novo/oms/1/itens/2/anexos/{arquivo}',
                         f'/financeiro-novo/documentos/rd/1/anexos/{arquivo}']:
                for sufixo, disposition in [('', 'attachment'),('?visualizar=1','inline')]:
                    with self.client.get(rota+sufixo) as response:
                        self.assertEqual(response.status_code,200)
                        self.assertTrue(response.headers['Content-Disposition'].startswith(disposition))
                        self.assertEqual(response.mimetype,'application/pdf')


if __name__ == '__main__':
    unittest.main()
