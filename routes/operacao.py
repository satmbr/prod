from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine
from datetime import date

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

@bp.get("/registro")
def registro():
    eh, fr = _fetch_listas()
    # filtros
    ini = request.args.get("ini")
    fim = request.args.get("fim")
    eh_id = request.args.get("eh_id")
    frente_id = request.args.get("frente_id")
    tipo = request.args.get("tipo")  # PLN / RLZ / None

    params = {}
    where_pln = []
    where_rlz = []

    if ini:
        where_pln.append("p.data >= :ini")
        where_rlz.append("r.data >= :ini")
        params["ini"] = ini
    if fim:
        where_pln.append("p.data <= :fim")
        where_rlz.append("r.data <= :fim")
        params["fim"] = fim
    if eh_id:
        where_pln.append("p.eh_id = :eh_id")
        where_rlz.append("r.eh_id = :eh_id")
        params["eh_id"] = eh_id
    if frente_id:
        where_pln.append("p.frente_id = :frente_id")
        where_rlz.append("r.frente_id = :frente_id")
        params["frente_id"] = frente_id

    sql_pln = f"""
      SELECT p.id, p.data, 'PLN' AS tipo, e.eh, f.frente, p.planejado AS qtd
      FROM producao_planejada p
      JOIN entre_house e ON e.id=p.eh_id
      JOIN frente_equipe f ON f.id=p.frente_id
      { 'WHERE ' + ' AND '.join(where_pln) if where_pln else '' }
    """
    sql_rlz = f"""
      SELECT r.id, r.data, 'RLZ' AS tipo, e.eh, f.frente, r.realizado AS qtd
      FROM producao_realizada r
      JOIN entre_house e ON e.id=r.eh_id
      JOIN frente_equipe f ON f.id=r.frente_id
      { 'WHERE ' + ' AND '.join(where_rlz) if where_rlz else '' }
    """

    if tipo == "PLN":
        sql = sql_pln + " ORDER BY data DESC, eh, frente"
    elif tipo == "RLZ":
        sql = sql_rlz + " ORDER BY data DESC, eh, frente"
    else:
        sql = f"({sql_pln}) UNION ALL ({sql_rlz}) ORDER BY data DESC, eh, frente, tipo"

    with get_engine().connect() as conn:
        resultados = conn.execute(text(sql), params).mappings().all()

    return render_template(
        "operacao/registro.html",
        subnav_links=_subnav("registro"),
        lista_eh=eh, lista_frente=fr,
        resultados=resultados,
        filtros={"ini":ini,"fim":fim,"eh_id":eh_id,"frente_id":frente_id,"tipo":tipo},
        today=date.today().isoformat(),
        msg=request.args.get("msg")
    )

@bp.post("/registro/planejada/create")
def reg_pln_create():
    data = request.form.get("data")
    eh_id = request.form.get("eh_id")
    frente_id = request.form.get("frente_id")
    planejado = request.form.get("planejado")
    if not (data and eh_id and frente_id and planejado):
        return redirect(url_for("operacao.registro", msg="Preencha todos os campos (Planejada)."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO producao_planejada (data, planejado, eh_id, frente_id)
                VALUES (:data, :qtd, :eh, :fr)
                ON CONFLICT (data, eh_id, frente_id) DO UPDATE
                SET planejado = EXCLUDED.planejado
            """), {"data":data, "qtd":int(planejado), "eh":eh_id, "fr":frente_id})
        return redirect(url_for("operacao.registro", msg="Planejada salva."))
    except Exception as e:
        return redirect(url_for("operacao.registro", msg=f"Erro Planejada: {e}"))

@bp.post("/registro/realizada/create")
def reg_rlz_create():
    data = request.form.get("data")
    eh_id = request.form.get("eh_id")
    frente_id = request.form.get("frente_id")
    realizado = request.form.get("realizado")
    if not (data and eh_id and frente_id and realizado):
        return redirect(url_for("operacao.registro", msg="Preencha todos os campos (Realizada)."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO producao_realizada (data, realizado, eh_id, frente_id)
                VALUES (:data, :qtd, :eh, :fr)
                ON CONFLICT (data, eh_id, frente_id) DO UPDATE
                SET realizado = EXCLUDED.realizado
            """), {"data":data, "qtd":int(realizado), "eh":eh_id, "fr":frente_id})
        return redirect(url_for("operacao.registro", msg="Realizada salva."))
    except Exception as e:
        return redirect(url_for("operacao.registro", msg=f"Erro Realizada: {e}"))

@bp.post("/registro/item/update")
def reg_item_update():
    tipo = request.form.get("tipo")  # PLN ou RLZ
    id_ = request.form.get("id")
    valor = request.form.get("valor")
    if not (tipo and id_ and valor and valor.isdigit()):
        return redirect(url_for("operacao.registro", msg="Dados inválidos no editar."))
    try:
        with get_engine().begin() as conn:
            if tipo == "PLN":
                conn.execute(text("UPDATE producao_planejada SET planejado=:v WHERE id=:id"),
                             {"v": int(valor), "id": id_})
            else:
                conn.execute(text("UPDATE producao_realizada SET realizado=:v WHERE id=:id"),
                             {"v": int(valor), "id": id_})
        return redirect(url_for("operacao.registro", msg="Registro atualizado."))
    except Exception as e:
        return redirect(url_for("operacao.registro", msg=f"Erro ao atualizar: {e}"))

@bp.post("/registro/item/delete")
def reg_item_delete():
    tipo = request.form.get("tipo")  # PLN ou RLZ
    id_ = request.form.get("id")
    if not (tipo and id_):
        return redirect(url_for("operacao.registro", msg="Dados inválidos no excluir."))
    try:
        with get_engine().begin() as conn:
            if tipo == "PLN":
                conn.execute(text("DELETE FROM producao_planejada WHERE id=:id"), {"id": id_})
            else:
                conn.execute(text("DELETE FROM producao_realizada WHERE id=:id"), {"id": id_})
        return redirect(url_for("operacao.registro", msg="Registro excluído."))
    except Exception as e:
        return redirect(url_for("operacao.registro", msg=f"Erro ao excluir: {e}"))

