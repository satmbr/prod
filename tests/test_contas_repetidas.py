import os
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from flask import session

os.environ.setdefault("SECRET_KEY", "chave-exclusiva-dos-testes-locais")
from app import app
from routes.financeiro_novo import perfil_pagamentos as views


class ContasRepetidasTests(unittest.TestCase):
    def setUp(self):
        self.engine = MagicMock()
        self.conn = self.engine.begin.return_value.__enter__.return_value
        self.conta = {"id": 39, "om_id": None, "om_item_id": None, "repetida_em": None}
        self.conn.execute.return_value.mappings.return_value.one.return_value = {
            **self.conta, "repetida_em": "2026-10-14"
        }

    def executar(self, *, restaurar=False, duplicidades=True, permissoes=None):
        with ExitStack() as stack:
            stack.enter_context(app.test_request_context(
                "/financeiro-novo/perfil-pagamentos/contas/39/repetida",
                method="POST", data={"restaurar": "1"} if restaurar else {}
            ))
            session["usuario_id"] = 7
            session["permissoes"] = permissoes if permissoes is not None else ["perfil_pagamentos:editar"]
            stack.enter_context(patch.object(views, "get_engine", return_value=self.engine))
            conta_mock = stack.enter_context(patch.object(views, "_conta", return_value=self.conta))
            dup = stack.enter_context(patch.object(views, "_duplicidades_om_conta", return_value=[{"om_id": 4}] if duplicidades else []))
            audit = stack.enter_context(patch.object(views, "registrar_evento"))
            response = views.pagamento_conta_repetida(39)
            return response, conta_mock, dup, audit

    def test_marcar_bloqueia_linha_e_registra_autoria(self):
        response, conta, dup, audit = self.executar()
        self.assertTrue(response.location.endswith("/perfil-pagamentos/repetidas"))
        conta.assert_called_once_with(self.conn, 39, bloquear=True)
        self.assertEqual(self.conn.execute.call_args.args[1]["usuario"], 7)
        self.assertFalse(self.conn.execute.call_args.args[1]["restaurar"])
        self.assertEqual(audit.call_args.kwargs["evento"], "MARCADA_COMO_REPETIDA")

    def test_nao_marca_conta_vinculada(self):
        self.conta["om_id"] = 9
        _, _, dup, audit = self.executar()
        self.conn.execute.assert_not_called()
        audit.assert_not_called()
        dup.assert_not_called()

    def test_nao_marca_quando_duplicidade_deixou_de_existir(self):
        _, _, _, audit = self.executar(duplicidades=False)
        self.conn.execute.assert_not_called()
        audit.assert_not_called()

    def test_restauracao_independe_da_existencia_da_duplicidade(self):
        _, _, dup, audit = self.executar(restaurar=True, duplicidades=False)
        dup.assert_not_called()
        self.assertTrue(self.conn.execute.call_args.args[1]["restaurar"])
        self.assertEqual(audit.call_args.kwargs["evento"], "REPETICAO_DESFEITA")

    def test_visualizador_nao_pode_marcar(self):
        from werkzeug.exceptions import Forbidden
        with self.assertRaises(Forbidden):
            self.executar(permissoes=["perfil_pagamentos:visualizar"])
        self.conn.execute.assert_not_called()

    def test_listas_separam_repetidas_e_preservam_filtros(self):
        for repetidas in (False, True):
            with self.subTest(repetidas=repetidas), app.test_request_context(
                "/financeiro-novo/perfil-pagamentos?q=teste&perfil_id=2&situacao=SEM_OM"
            ):
                session["usuario_id"] = 7
                session["permissoes"] = ["perfil_pagamentos:visualizar"]
                engine = MagicMock()
                conn = engine.connect.return_value.__enter__.return_value
                with patch.object(views, "get_engine", return_value=engine), patch.object(views, "render_template", return_value="ok") as render:
                    views.pagamentos_painel(repetidas=repetidas)
                query, params = conn.execute.call_args_list[1].args
                self.assertIn("c.repetida_em IS NOT NULL" if repetidas else "c.repetida_em IS NULL", str(query))
                self.assertIn("c.om_id IS NULL", str(query))
                self.assertEqual(params, {"busca": "%teste%", "perfil_id": 2})
                self.assertEqual(render.call_args.kwargs["repetidas"], repetidas)

    def test_tela_repetidas_renderiza_acoes_e_dialogo(self):
        from jinja2 import ChoiceLoader, DictLoader, Environment
        env = Environment(loader=ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            app.jinja_loader
        ]))
        env.globals["url_for"] = lambda endpoint, **kwargs: "/" + endpoint
        with app.test_request_context("/"):
            html = env.get_template("financeiro_novo/pagamentos_painel.html").render(
                repetidas=True, current_user_permissions=["auth:administrar"],
                contas=[], perfis=[], oms_rascunho=[], busca="", perfil_id="", situacao="",
                bucket_ativo=False, portal_base_url=""
            )
        self.assertIn("Contas repetidas", html)
        self.assertIn("Marcar como repetida", html)
        self.assertIn("Replicar mesmo assim", html)
        self.assertNotIn("Perfis e portais de arquivos", html)

