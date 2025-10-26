from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine

bp = Blueprint("equipamentos", __name__)

# ----------------------------
# Helpers
# ----------------------------
def _subnav(active: str):
    return [
        {"text": "Cadastro",   "href": url_for("equipamentos.cadastro"),   "active": active == "cadastro"},
        {"text": "PartDiaria", "href": url_for("equipamentos.partdiaria"), "active": active == "partdiaria"},
    ]

def _fetch_listas():
    """Carrega listas básicas para os selects da página de cadastro."""
    with get_engine().connect() as conn:
        maquinas = conn.execute(text("""
            SELECT id, tag, descricao, ativo
            FROM maquina
            ORDER BY tag
        """)).mappings().all()

        pontos = conn.execute(text("""
            SELECT pm.id,
                   pm.codigo,
                   pm.unidade,
                   pm.ativo,
                   pm.maquina_id,
                   m.tag  AS maquina_tag
            FROM ponto_medicao pm
            JOIN maquina m ON m.id = pm.maquina_id
            ORDER BY m.tag, pm.codigo
        """)).mappings().all()
    return maquinas, pontos

# ----------------------------
# Páginas
# ----------------------------
@bp.get("/")
def index():
    return render_template("equipamentos/index.html", subnav_links=_subnav(""))

@bp.get("/cadastro")
def cadastro():
    maquinas, pontos = _fetch_listas()
    return render_template(
        "equipamentos/cadastro.html",
        subnav_links=_subnav("cadastro"),
        maquinas=maquinas,
        pontos=pontos,
        msg=request.args.get("msg")
    )

@bp.get("/partdiaria")
def partdiaria():
    # manteremos como placeholder por enquanto
    return render_template("equipamentos/partdiaria.html", subnav_links=_subnav("partdiaria"),
                           filtros={}, resultados=[], today=None, msg=request.args.get("msg"))

# ----------------------------
# CRUD · MÁQUINA
# ----------------------------
@bp.post("/cadastro/maquina/create")
def maq_create():
    tag = (request.form.get("tag") or "").strip()
    descricao = (request.form.get("descricao") or "").strip()
    ativo = True if request.form.get("ativo") == "on" else False
    if not tag or not descricao:
        return redirect(url_for("equipamentos.cadastro", msg="Informe TAG e Descrição da máquina."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO maquina (tag, descricao, ativo)
                VALUES (:tag, :descricao, :ativo)
            """), {"tag": tag, "descricao": descricao, "ativo": ativo})
        return redirect(url_for("equipamentos.cadastro", msg="Máquina cadastrada."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao cadastrar máquina: {e}"))

@bp.post("/cadastro/maquina/update")
def maq_update():
    id_ = request.form.get("id")
    nova_tag = (request.form.get("nova_tag") or "").strip()
    nova_desc = (request.form.get("nova_descricao") or "").strip()
    ativo = True if request.form.get("ativo") == "on" else False
    if not id_:
        return redirect(url_for("equipamentos.cadastro", msg="Selecione a máquina para atualizar."))
    if not nova_tag and not nova_desc and request.form.get("ativo") is None:
        return redirect(url_for("equipamentos.cadastro", msg="Nada para atualizar."))
    try:
        sets = []
        params = {"id": id_}
        if nova_tag:
            sets.append("tag=:tag"); params["tag"] = nova_tag
        if nova_desc:
            sets.append("descricao=:desc"); params["desc"] = nova_desc
        sets.append("ativo=:ativo"); params["ativo"] = ativo

        with get_engine().begin() as conn:
            conn.execute(text(f"UPDATE maquina SET {', '.join(sets)} WHERE id=:id"), params)
        return redirect(url_for("equipamentos.cadastro", msg="Máquina atualizada."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao atualizar máquina: {e}"))

@bp.post("/cadastro/maquina/delete")
def maq_delete():
    id_ = request.form.get("id")
    if not id_:
        return redirect(url_for("equipamentos.cadastro", msg="Selecione a máquina a excluir."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM maquina WHERE id=:id"), {"id": id_})
        return redirect(url_for("equipamentos.cadastro", msg="Máquina excluída."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao excluir máquina: {e}"))

# ----------------------------
# CRUD · PONTO DE MEDIÇÃO
# ----------------------------
@bp.post("/cadastro/ponto/create")
def ponto_create():
    maquina_id = request.form.get("maquina_id")
    codigo = (request.form.get("codigo") or "").strip()
    unidade = (request.form.get("unidade") or "").strip()
    ativo = True if request.form.get("ativo") == "on" else False
    if not maquina_id or not codigo or not unidade:
        return redirect(url_for("equipamentos.cadastro", msg="Informe Máquina, Código e Unidade do ponto."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO ponto_medicao (maquina_id, codigo, unidade, ativo)
                VALUES (:maquina_id, :codigo, :unidade, :ativo)
            """), {"maquina_id": maquina_id, "codigo": codigo, "unidade": unidade, "ativo": ativo})
        return redirect(url_for("equipamentos.cadastro", msg="Ponto de medição cadastrado."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao cadastrar ponto: {e}"))

@bp.post("/cadastro/ponto/update")
def ponto_update():
    id_ = request.form.get("id")
    maquina_id = request.form.get("maquina_id")  # opcional: permite mover para outra máquina
    codigo = (request.form.get("codigo") or "").strip()
    unidade = (request.form.get("unidade") or "").strip()
    ativo = True if request.form.get("ativo") == "on" else False
    if not id_:
        return redirect(url_for("equipamentos.cadastro", msg="Selecione o ponto a atualizar."))
    try:
        sets, params = [], {"id": id_}
        if maquina_id:
            sets.append("maquina_id=:maquina_id"); params["maquina_id"] = maquina_id
        if codigo:
            sets.append("codigo=:codigo"); params["codigo"] = codigo
        if unidade:
            sets.append("unidade=:unidade"); params["unidade"] = unidade
        sets.append("ativo=:ativo"); params["ativo"] = ativo

        with get_engine().begin() as conn:
            conn.execute(text(f"UPDATE ponto_medicao SET {', '.join(sets)} WHERE id=:id"), params)
        return redirect(url_for("equipamentos.cadastro", msg="Ponto atualizado."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao atualizar ponto: {e}"))

@bp.post("/cadastro/ponto/delete")
def ponto_delete():
    id_ = request.form.get("id")
    if not id_:
        return redirect(url_for("equipamentos.cadastro", msg="Selecione o ponto a excluir."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM ponto_medicao WHERE id=:id"), {"id": id_})
        return redirect(url_for("equipamentos.cadastro", msg="Ponto excluído."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao excluir ponto: {e}"))
