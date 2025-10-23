from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine

bp = Blueprint("operacao", __name__)

def _subnav(active: str):
    return [
        {"text": "Produção", "href": url_for("operacao.producao"), "active": active == "producao"},
        {"text": "Registro",  "href": url_for("operacao.registro"),  "active": active == "registro"},
        {"text": "Cadastro",  "href": url_for("operacao.cadastro"),  "active": active == "cadastro"},
    ]

def _fetch_listas():
    with get_engine().connect() as conn:
        eh = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()
    return eh, fr

# ===== GETs =====
@bp.get("/")
def index():
    return render_template("operacao/index.html", subnav_links=_subnav(""))

@bp.get("/producao")
def producao():
    # template com acento 'produção.html' — renomeie para 'producao.html' se preferir
    return render_template("operacao/producao.html", subnav_links=_subnav("producao"))

@bp.get("/registro")
def registro():
    return render_template("operacao/registro.html", subnav_links=_subnav("registro"))

@bp.get("/cadastro")
def cadastro():
    eh, fr = _fetch_listas()
    msg = request.args.get("msg")
    return render_template("operacao/cadastro.html",
                           subnav_links=_subnav("cadastro"),
                           lista_eh=eh, lista_frente=fr, msg=msg)

# ===== EH (POST) =====
@bp.post("/cadastro/eh/create")
def eh_create():
    eh = (request.form.get("eh") or "").strip()
    if not eh:
        return redirect(url_for("operacao.cadastro", msg="Informe a EH."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO entre_house (eh) VALUES (:eh)"), {"eh": eh})
        return redirect(url_for("operacao.cadastro", msg="EH cadastrada."))
    except Exception as e:
        return redirect(url_for("operacao.cadastro", msg=f"Erro ao cadastrar EH: {e}"))

@bp.post("/cadastro/eh/update")
def eh_update():
    id_ = request.form.get("id")
    novo = (request.form.get("novo_eh") or "").strip()
    if not id_ or not novo:
        return redirect(url_for("operacao.cadastro", msg="Selecione a EH e informe o novo nome."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE entre_house SET eh=:novo WHERE id=:id"),
                         {"novo": novo, "id": id_})
        return redirect(url_for("operacao.cadastro", msg="EH atualizada."))
    except Exception as e:
        return redirect(url_for("operacao.cadastro", msg=f"Erro ao atualizar EH: {e}"))

@bp.post("/cadastro/eh/delete")
def eh_delete():
    id_ = request.form.get("id")
    if not id_:
        return redirect(url_for("operacao.cadastro", msg="Selecione a EH a excluir."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM entre_house WHERE id=:id"), {"id": id_})
        return redirect(url_for("operacao.cadastro", msg="EH excluída."))
    except Exception as e:
        return redirect(url_for("operacao.cadastro", msg=f"Erro ao excluir EH: {e}"))

# ===== Frente (POST) =====
@bp.post("/cadastro/frente/create")
def frente_create():
    frente = (request.form.get("frente") or "").strip()
    if not frente:
        return redirect(url_for("operacao.cadastro", msg="Informe a Frente."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO frente_equipe (frente) VALUES (:frente)"),
                         {"frente": frente})
        return redirect(url_for("operacao.cadastro", msg="Frente cadastrada."))
    except Exception as e:
        return redirect(url_for("operacao.cadastro", msg=f"Erro ao cadastrar Frente: {e}"))

@bp.post("/cadastro/frente/update")
def frente_update():
    id_ = request.form.get("id")
    novo = (request.form.get("nova_frente") or "").strip()
    if not id_ or not novo:
        return redirect(url_for("operacao.cadastro", msg="Selecione a Frente e informe o novo nome."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE frente_equipe SET frente=:novo WHERE id=:id"),
                         {"novo": novo, "id": id_})
        return redirect(url_for("operacao.cadastro", msg="Frente atualizada."))
    except Exception as e:
        return redirect(url_for("operacao.cadastro", msg=f"Erro ao atualizar Frente: {e}"))

@bp.post("/cadastro/frente/delete")
def frente_delete():
    id_ = request.form.get("id")
    if not id_:
        return redirect(url_for("operacao.cadastro", msg="Selecione a Frente a excluir."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM frente_equipe WHERE id=:id"), {"id": id_})
        return redirect(url_for("operacao.cadastro", msg="Frente excluída."))
    except Exception as e:
        return redirect(url_for("operacao.cadastro", msg=f"Erro ao excluir Frente: {e}"))
