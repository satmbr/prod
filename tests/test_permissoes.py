import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _nome_decorator(no):
    if isinstance(no, ast.Call):
        return _nome_decorator(no.func)
    if isinstance(no, ast.Attribute):
        return f"{_nome_decorator(no.value)}.{no.attr}"
    if isinstance(no, ast.Name):
        return no.id
    return ""


class PermissoesPerfilTests(unittest.TestCase):
    def test_catalogo_cobre_todas_as_permissoes_usadas_nas_rotas(self):
        from routes.auth import PERMISSOES_SISTEMA

        catalogo = {(modulo, acao) for modulo, acao, _ in PERMISSOES_SISTEMA}
        usadas = {("auth", "administrar")}
        for arquivo in (ROOT / "routes").rglob("*.py"):
            if arquivo.name.endswith(".py.py"):
                continue
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            constantes = {}
            for no in arvore.body:
                if (
                    isinstance(no, ast.Assign)
                    and len(no.targets) == 1
                    and isinstance(no.targets[0], ast.Name)
                    and isinstance(no.value, ast.Constant)
                    and isinstance(no.value.value, str)
                ):
                    constantes[no.targets[0].id] = no.value.value
            for no in ast.walk(arvore):
                if (
                    not isinstance(no, ast.Call)
                    or _nome_decorator(no.func) != "permission_required"
                    or len(no.args) < 2
                ):
                    continue
                valores = []
                for argumento in no.args[:2]:
                    if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
                        valores.append(argumento.value)
                    elif isinstance(argumento, ast.Name) and argumento.id in constantes:
                        valores.append(constantes[argumento.id])
                if len(valores) == 2:
                    usadas.add(tuple(valores))
        self.assertEqual(set(), usadas - catalogo)
        self.assertEqual(38, len(catalogo))

    def test_tela_tem_controle_global_por_modulo_e_individual(self):
        tela = (ROOT / "templates" / "auth" / "perfil_permissoes.html").read_text(
            encoding="utf-8"
        )
        for termo in (
            "Liberar tudo",
            "Bloquear tudo",
            "module-toggle",
            "permission-checkbox",
            "Buscar módulo, página, ação ou descrição",
            "Salvar permissões",
        ):
            self.assertIn(termo, tela)

    def test_servidor_suporta_liberar_e_bloquear_tudo(self):
        rota = (ROOT / "routes" / "auth.py").read_text(encoding="utf-8")
        self.assertIn('acao_formulario == "liberar_tudo"', rota)
        self.assertIn('acao_formulario == "bloquear_tudo"', rota)
        self.assertIn("sincronizar_catalogo_permissoes(conn)", rota)
        self.assertIn('session["permissoes"] = carregar_permissoes_usuario', rota)

    def test_migracao_contem_modulos_novos(self):
        migracao = (ROOT / "migrations" / "029_catalogo_permissoes_completo.sql").read_text(
            encoding="utf-8"
        )
        for modulo in ("perfil_pagamentos", "bot", "fornecedores"):
            self.assertIn(f"('{modulo}'", migracao)


if __name__ == "__main__":
    unittest.main()
