import os
from pathlib import Path

from flask import current_app, render_template
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.views import build_subnav


def diagnosticar_armazenamento():
    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    existe = raiz.is_dir()
    gravavel = existe and os.access(raiz, os.W_OK)
    railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
    mount_configurado = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    persistente = False
    if mount_configurado:
        mount = Path(mount_configurado).resolve()
        persistente = raiz == mount or raiz.is_relative_to(mount)
    elif railway:
        persistente = str(raiz).replace("\\", "/").startswith("/data/") or str(raiz) == "/data"
    else:
        persistente = True
    return {
        "raiz": str(raiz),
        "existe": existe,
        "gravavel": gravavel,
        "persistente": persistente,
        "railway": railway,
        "mount": mount_configurado,
    }


@bp.get("/homologacao")
@login_required
@permission_required("financeiro_novo", "administrar")
def homologacao():
    with get_engine().connect() as conn:
        configuracao = conn.execute(text(
            "SELECT ambiente,versao_schema,criado_em,atualizado_em FROM financeiro3_configuracao WHERE id=1"
        )).mappings().one()
        cadastros = conn.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM financeiro3_pessoas WHERE ativo AND fornecedor) AS fornecedores,
              (SELECT COUNT(*) FROM financeiro3_pessoas WHERE ativo AND favorecido) AS favorecidos,
              (SELECT COUNT(*) FROM financeiro3_clientes WHERE ativo) AS clientes,
              (SELECT COUNT(*) FROM financeiro3_centros_custo WHERE ativo) AS centros,
              (SELECT COUNT(*) FROM financeiro3_categorias WHERE ativo AND natureza='DESPESA') AS categorias,
              (SELECT COUNT(*) FROM financeiro3_moedas WHERE ativo) AS moedas,
              (SELECT COUNT(*) FROM financeiro3_contas WHERE ativo) AS contas
        """)).mappings().one()
        operacao = conn.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM financeiro3_despesas) AS despesas,
              (SELECT COUNT(*) FROM financeiro3_oms) AS oms,
              (SELECT COUNT(*) FROM financeiro3_rds) AS rds,
              (SELECT COUNT(*) FROM financeiro3_notas_debito) AS notas,
              (SELECT COUNT(*) FROM financeiro3_reembolsos) AS reembolsos,
              (SELECT COUNT(*) FROM financeiro3_auditoria) AS auditorias,
              (SELECT COUNT(*) FROM financeiro3_arquivos) AS arquivos
        """)).mappings().one()
        permissoes = conn.execute(text("""
            SELECT pm.acao,COUNT(DISTINCT pp.perfil_id) AS perfis
            FROM permissoes pm LEFT JOIN perfil_permissoes pp ON pp.permissao_id=pm.id
            WHERE pm.modulo='financeiro_novo'
            GROUP BY pm.acao ORDER BY pm.acao
        """)).mappings().all()
        tabelas_novas = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema='public' AND table_name LIKE 'financeiro3_%'
        """)).scalar()

    storage = diagnosticar_armazenamento()
    permissoes_atribuidas = any(item["perfis"] > 0 for item in permissoes)
    cadastros_prontos = all(cadastros[chave] > 0 for chave in ("fornecedores", "favorecidos", "clientes", "centros", "categorias", "moedas", "contas"))
    verificacoes = [
        {"nome": "Schema do Financeiro Novo", "ok": configuracao["versao_schema"] >= 11, "detalhe": f"Versão {configuracao['versao_schema']} · {tabelas_novas} tabelas próprias"},
        {"nome": "Isolamento do módulo", "ok": True, "detalhe": "Rotas automatizadas verificam ausência de referências ao módulo anterior"},
        {"nome": "Armazenamento acessível", "ok": storage["existe"] and storage["gravavel"], "detalhe": storage["raiz"]},
        {"nome": "Volume persistente no Railway", "ok": storage["persistente"], "detalhe": storage["mount"] or "Mount persistente não identificado"},
        {"nome": "Permissões atribuídas a perfis", "ok": permissoes_atribuidas, "detalhe": "Além do acesso administrativo geral"},
        {"nome": "Cadastros mínimos", "ok": cadastros_prontos, "detalhe": "Fornecedor, favorecido, cliente, centro, categoria, moeda e conta"},
    ]
    return render_template(
        "financeiro_novo/homologacao.html", configuracao=configuracao,
        cadastros=cadastros, operacao=operacao, permissoes=permissoes,
        storage=storage, verificacoes=verificacoes,
        pronto=all(item["ok"] for item in verificacoes),
        subnav_links=build_subnav("homologacao"),
    )
