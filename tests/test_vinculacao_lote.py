import os
import unittest
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret")
from app import create_app
from routes.financeiro_novo import perfil_pagamentos as views


class VinculacaoLoteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s.update(usuario_id=1, ultimo_acesso=9999999999,
                     permissoes=['perfil_pagamentos:editar','financeiro_novo:editar'])
        self.engine = MagicMock()
        self.read = self.engine.connect.return_value.__enter__.return_value
        self.write = self.engine.begin.return_value.__enter__.return_value
        self.conta = dict(id=8, numero='CP-8', perfil_id=2, storage_prefix='perfil/2',
                          drive_file_id='a'*32, drive_nome_atual='recibo.pdf',
                          repetida_em=None, om_id=None, data_documento=date(2026,11,13),
                          descricao='Hospedagem', valor=Decimal('100.00'))
        self.read.execute.return_value.mappings.return_value.first.return_value = self.conta
        self.om = dict(id=3,numero_om='OM-3',status='RASCUNHO',centro_custo_id=2)
        self.dup = dict(om_id=4, numero_om='OM-4', item_id=99,numero_linha=7,
                        data_despesa=date(2026,11,13),descricao='Anterior',valor=Decimal('100.00'))
        self.path = MagicMock()
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(views,'get_engine',return_value=self.engine))
        self.stack.enter_context(patch.object(views,'_conta',return_value=self.conta))
        self.duplicidades = self.stack.enter_context(patch.object(views,'_duplicidades_om_conta',return_value=[]))
        self.download = self.stack.enter_context(patch.object(views,'baixar_arquivo',return_value={'conteudo':b'pdf','mimeType':'application/pdf'}))
        self.stack.enter_context(patch('routes.financeiro_novo.reembolsos._preparar_anexo',return_value=(None,None,None,self.path)))
        self.stack.enter_context(patch('routes.financeiro_novo.reembolsos._vincular_anexo',return_value=5))
        self.audit = self.stack.enter_context(patch.object(views,'registrar_evento'))
        self.stack.enter_context(patch('routes.financeiro_novo.services.quitacao_om.reconciliar_quitacao_om',return_value=[8]))
        self.sync = self.stack.enter_context(patch.object(views,'sincronizar_arquivo_da_conta'))
        self.write.execute.return_value.mappings.return_value.first.return_value = self.om
        self.write.execute.return_value.scalar.return_value = 2
        self.write.execute.return_value.mappings.return_value.one.return_value = {'id':10}

    def enviar(self, confirmar=False, json=True):
        return self.client.post('/financeiro-novo/perfil-pagamentos/contas/8/replicar-om',
                                data={'om_id':'3','confirmar_duplicidade':'1' if confirmar else '0'},
                                headers={'Accept':'application/json'} if json else {})

    def test_tela_lista_todas_nao_vinculadas_inclusive_repetidas(self):
        self.read.execute.return_value.mappings.return_value.all.return_value = []
        r=self.client.get('/financeiro-novo/perfil-pagamentos/vincular-varias')
        self.assertEqual(r.status_code,200)
        sql=str(self.read.execute.call_args_list[0].args[0])
        self.assertIn('c.om_id IS NULL AND c.excluida_em IS NULL',sql)
        self.assertNotIn('LIMIT',sql)
        self.assertNotIn('c.repetida_em IS NULL',sql)
        self.assertIn('Revisar e vincular selecionadas',r.get_data(as_text=True))

    def test_tela_exibe_contas_e_om_com_escape(self):
        conta = {**self.conta, 'perfil_nome':'Equipe A', 'data_vencimento':date(2026,11,20),
                 'descricao':'<script>teste</script>', 'repetida_em':date(2026,11,13)}
        self.read.execute.return_value.mappings.return_value.all.side_effect = [
            [conta], [{**self.om, 'favorecido':'Maria'}]]
        r=self.client.get('/financeiro-novo/perfil-pagamentos/vincular-varias')
        html=r.get_data(as_text=True)
        self.assertEqual(r.status_code,200)
        self.assertIn('data-conta-id="8"',html)
        self.assertIn('Marcada como repetida',html)
        self.assertIn('OM OM-3',html)
        self.assertIn('&lt;script&gt;teste&lt;/script&gt;',html)
        self.assertNotIn('<script>teste</script>',html)

    def test_exige_ambas_permissoes(self):
        for permissions in [['perfil_pagamentos:editar'],['financeiro_novo:editar']]:
            with self.client.session_transaction() as s: s['permissoes']=permissions
            self.assertEqual(self.client.get('/financeiro-novo/perfil-pagamentos/vincular-varias').status_code,403)
            self.assertEqual(self.enviar().status_code,403)
        self.engine.begin.assert_not_called()

    def test_duplicidade_pede_decisao_sem_baixar_arquivo(self):
        self.duplicidades.return_value=[self.dup]
        r=self.enviar()
        self.assertEqual(r.status_code,409)
        self.assertEqual(r.json['status'],'duplicidade')
        self.assertEqual(r.json['duplicidades'][0]['numero_om'],'OM-4')
        self.download.assert_not_called()
        self.engine.begin.assert_not_called()

    def test_revalida_duplicidade_na_transacao_e_limpa_apenas_temporario(self):
        self.duplicidades.side_effect=[[],[self.dup]]
        r=self.enviar()
        self.assertEqual(r.status_code,409)
        self.path.unlink.assert_called_once_with(missing_ok=True)
        self.audit.assert_not_called()

    def test_vincula_com_confirmacao_explicita_e_auditoria(self):
        self.duplicidades.return_value=[self.dup]
        r=self.enviar(confirmar=True)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['status'],'vinculada')
        self.assertEqual(r.json['om_id'],3)
        self.assertEqual(self.audit.call_args.kwargs['evento'],'REPLICADA_PARA_OM')
        self.path.unlink.assert_not_called()

    def test_vincula_sem_repeticoes(self):
        r=self.enviar()
        self.assertEqual(r.json['status'],'vinculada')
        self.assertEqual(self.duplicidades.call_count,2)

    def test_om_rejeitada_recebe_vinculacao_individual_e_lote(self):
        self.om['status'] = 'REJEITADA'
        self.assertEqual(self.enviar().json['status'], 'vinculada')
        self.assertEqual(self.enviar(json=False).status_code, 302)

    def test_listas_individual_e_lote_incluem_rejeitadas(self):
        from flask import session
        for endpoint in (views.pagamentos_painel, views.pagamentos_vincular_varias):
            with self.app.test_request_context('/'):
                session['usuario_id'] = 1
                session['permissoes'] = ['auth:administrar']
                self.read.execute.reset_mock()
                with patch.object(views, 'render_template', return_value='ok'):
                    endpoint()
                consultas = [str(call.args[0]) for call in self.read.execute.call_args_list]
                self.assertTrue(any("o.status IN ('RASCUNHO','REJEITADA')" in sql for sql in consultas))

    def test_om_fora_de_rascunho_nao_recebe_lancamento(self):
        self.om['status']='EM_APROVACAO'
        r=self.enviar()
        self.assertEqual(r.status_code,400)
        self.audit.assert_not_called()
        self.path.unlink.assert_called_once()

    def test_conta_ja_vinculada_nao_repete_envio(self):
        self.conta['om_id']=3
        r=self.enviar()
        self.assertEqual(r.status_code,400)
        self.download.assert_not_called()
        self.engine.begin.assert_not_called()

    def test_falha_sincronizacao_apos_commit_nao_apaga_recibo(self):
        self.sync.side_effect=RuntimeError('storage indisponivel')
        with self.assertLogs(self.app.logger,level='ERROR'):
            r=self.enviar()
        self.assertEqual(r.json['status'],'vinculada')
        self.path.unlink.assert_not_called()

    def test_fluxo_individual_continua_redirecionando(self):
        r=self.enviar(json=False)
        self.assertEqual(r.status_code,302)
        self.assertTrue(r.location.endswith('/perfil-pagamentos'))

    def test_csrf_obrigatorio_no_envio_em_lote(self):
        self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.enviar().status_code,400)
        self.engine.begin.assert_not_called()


if __name__=='__main__': unittest.main()
