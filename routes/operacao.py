from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine
from datetime import date

bp = Blueprint("operacao", __name__)

# ----------------------------
# Helpers
# ----------------------------
def _subnav(active: str):
    return [
        {"text": "Produção", "href": url_for("operacao.producao"), "active": active == "producao"},
        {"text": "Registro",  "href": url_for("operacao.registro"),  "active": active == "registro"},
        {"text": "Cadastro",  "href": url_for("operacao.cadastro"),  "active": active == "cadastro"},
    ]

def _fetch_listas():
    """Carrega listas de EH e Frentes para selects."""
    with get_engine().connect() as conn:
        eh = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()
    return eh, fr

# ----------------------------
# GETs básicos
# ----------------------------
@bp.get("/")
def index():
    return render_template("operacao/index.html", subnav_links=_subnav(""))

# remove itens None
def _clean_nav(nav): return [n for n in nav if n]
# ----------------------------------------------------------------

@bp.get("/producao")
def producao():
    """Tela de acompanhamento de produção + parte diária (2 contêineres)."""
    sel_eh = request.args.get("eh")      # id da entre_house
    sel_fr = request.args.get("fr")      # id da frente_equipe
    sel_dt = request.args.get("dt") or date.today().isoformat()

    sel_maq = request.args.get("maq")    # para parte diária
    sel_dt_pd = request.args.get("dt_pd") or sel_dt

    with get_engine().connect() as conn:
        # listas de seleção
        eh_list = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr_list = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()
        maq_list = conn.execute(text("""
            SELECT id, tag, descricao FROM maquina WHERE ativo IS TRUE ORDER BY tag
        """)).mappings().all()

        # -------------------- BLOCO 1: PRODUÇÃO (tabela + gráfico) --------------------
        prod_rows = []
        chart_prod = {"labels": [], "prev_dia": [], "real_dia": [], "prev_tot": [], "real_tot": []}

        if sel_eh and sel_fr:
            sql = text("""
                WITH dias AS (
                    SELECT gs::date AS d
                    FROM generate_series(date_trunc('month', :refdt::date)::date,
                                         :refdt::date, interval '1 day') gs
                ),
                pl AS (
                    SELECT data::date, SUM(planejado) AS planejado
                    FROM producao_planejada
                    WHERE eh_id=:eh AND frente_id=:fr
                    GROUP BY data
                ),
                rl AS (
                    SELECT data::date, SUM(realizado) AS realizado
                    FROM producao_realizada
                    WHERE eh_id=:eh AND frente_id=:fr
                    GROUP BY data
                ),
                base AS (
                    SELECT d.d AS data,
                           COALESCE(pl.planejado, 0) AS previsto_dia,
                           COALESCE(rl.realizado, 0) AS realizado_dia
                    FROM dias d
                    LEFT JOIN pl ON pl.data = d.d
                    LEFT JOIN rl ON rl.data = d.d
                    ORDER BY d.d
                )
                SELECT data,
                       previsto_dia,
                       SUM(previsto_dia) OVER (ORDER BY data) AS previsto_total,
                       realizado_dia,
                       SUM(realizado_dia) OVER (ORDER BY data) AS realizado_total
                FROM base
                ORDER BY data
            """)
            params = {"eh": sel_eh, "fr": sel_fr, "refdt": sel_dt}
            prod = conn.execute(sql, params).mappings().all()

            # computa dif e atraso (dif/850)
            for r in prod:
                dif = (r["realizado_total"] or 0) - (r["previsto_total"] or 0)
                atraso = (dif / 850.0) if 850 else 0.0
                prod_rows.append({
                    "data": r["data"],
                    "previsto_dia": r["previsto_dia"],
                    "previsto_total": r["previsto_total"],
                    "realizado_dia": r["realizado_dia"],
                    "realizado_total": r["realizado_total"],
                    "dif": dif,
                    "atraso": atraso,
                })
                # dados do gráfico
                chart_prod["labels"].append(r["data"].strftime("%d/%m"))
                chart_prod["prev_dia"].append(float(r["previsto_dia"]))
                chart_prod["real_dia"].append(float(r["realizado_dia"]))
                chart_prod["prev_tot"].append(float(r["previsto_total"]))
                chart_prod["real_tot"].append(float(r["realizado_total"]))

        # -------------------- BLOCO 2: PARTE DIÁRIA (lista + gráfico) --------------------
        pd_lista = []
        pd_graf  = {"labels": [], "horas": []}  # acumulado de horas por atividade (no dia)
        if sel_maq and sel_dt_pd:
            # lista do dia
            pd_sql = text("""
                SELECT pd.id,
                       a.nome AS evento,
                       to_char(pd.hora_inicio, 'HH24:MI') AS inicio,
                       to_char(pd.hora_fim, 'HH24:MI')    AS fim,
                       EXTRACT(EPOCH FROM (pd.hora_fim - pd.hora_inicio))/3600.0 AS horas
                FROM parte_diaria pd
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.maquina_id = :maq
                  AND pd.data = :d
                ORDER BY pd.hora_inicio
            """)
            pd_lista = conn.execute(pd_sql, {"maq": sel_maq, "d": sel_dt_pd}).mappings().all()

            # agrupado por atividade
            pd_agg = conn.execute(text("""
                SELECT a.nome AS evento,
                       ROUND(EXTRACT(EPOCH FROM SUM(pd.hora_fim - pd.hora_inicio))/3600.0, 2) AS horas
                FROM parte_diaria pd
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.maquina_id = :maq
                  AND pd.data = :d
                GROUP BY a.nome
                ORDER BY horas DESC
            """), {"maq": sel_maq, "d": sel_dt_pd}).mappings().all()

            for r in pd_agg:
                pd_graf["labels"].append(r["evento"])
                pd_graf["horas"].append(float(r["horas"] or 0))

    return render_template(
        "operacao/producao.html",
        subnav_links=_clean_nav(_subnav("producao")),
        eh_list=eh_list, fr_list=fr_list, maq_list=maq_list,
        sel_eh=sel_eh, sel_fr=sel_fr, sel_dt=sel_dt,
        sel_maq=sel_maq, sel_dt_pd=sel_dt_pd,
        prod_rows=prod_rows, chart_prod=chart_prod,
        pd_lista=pd_lista, pd_graf=pd_graf,
        msg=request.args.get("msg")
    )

@bp.get("/cadastro")
def cadastro():
    eh, fr = _fetch_listas()
    return render_template(
        "operacao/cadastro.html",
        subnav_links=_subnav("cadastro"),
        lista_eh=eh,
        lista_frente=fr,
        msg=request.args.get("msg"),
    )

# ----------------------------
# CADASTRO · EH (POST)
# ----------------------------
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

# ----------------------------
# CADASTRO · FRENTE (POST)
# ----------------------------
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

# ----------------------------
# REGISTRO · GET com filtros
# ----------------------------
@bp.get("/registro")
def registro():
    eh, fr = _fetch_listas()
    # filtros
    ini = request.args.get("ini")
    fim = request.args.get("fim")
    eh_id = request.args.get("eh_id")
    frente_id = request.args.get("frente_id")
    tipo = request.args.get("tipo")  # PLN / RLZ / None

    params, where_pln, where_rlz = {}, [], []

    if ini:
        where_pln.append("p.data >= :ini"); where_rlz.append("r.data >= :ini"); params["ini"] = ini
    if fim:
        where_pln.append("p.data <= :fim"); where_rlz.append("r.data <= :fim"); params["fim"] = fim
    if eh_id:
        where_pln.append("p.eh_id = :eh_id"); where_rlz.append("r.eh_id = :eh_id"); params["eh_id"] = eh_id
    if frente_id:
        where_pln.append("p.frente_id = :frente_id"); where_rlz.append("r.frente_id = :frente_id"); params["frente_id"] = frente_id

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
        msg=request.args.get("msg"),
    )

# ----------------------------
# REGISTRO · Planejada/Realizada (UPSERT)
# ----------------------------
@bp.post("/registro/planejada/create")
def reg_pln_create():
    data_ = request.form.get("data")
    eh_id = request.form.get("eh_id")
    frente_id = request.form.get("frente_id")
    planejado = request.form.get("planejado")
    if not (data_ and eh_id and frente_id and planejado):
        return redirect(url_for("operacao.registro", msg="Preencha todos os campos (Planejada)."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO producao_planejada (data, planejado, eh_id, frente_id)
                VALUES (:data, :qtd, :eh, :fr)
                ON CONFLICT (data, eh_id, frente_id) DO UPDATE
                SET planejado = EXCLUDED.planejado
            """), {"data": data_, "qtd": int(planejado), "eh": eh_id, "fr": frente_id})
        return redirect(url_for("operacao.registro", msg="Planejada salva."))
    except Exception as e:
        return redirect(url_for("operacao.registro", msg=f"Erro Planejada: {e}"))

@bp.post("/registro/realizada/create")
def reg_rlz_create():
    data_ = request.form.get("data")
    eh_id = request.form.get("eh_id")
    frente_id = request.form.get("frente_id")
    realizado = request.form.get("realizado")
    if not (data_ and eh_id and frente_id and realizado):
        return redirect(url_for("operacao.registro", msg="Preencha todos os campos (Realizada)."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO producao_realizada (data, realizado, eh_id, frente_id)
                VALUES (:data, :qtd, :eh, :fr)
                ON CONFLICT (data, eh_id, frente_id) DO UPDATE
                SET realizado = EXCLUDED.realizado
            """), {"data": data_, "qtd": int(realizado), "eh": eh_id, "fr": frente_id})
        return redirect(url_for("operacao.registro", msg="Realizada salva."))
    except Exception as e:
        return redirect(url_for("operacao.registro", msg=f"Erro Realizada: {e}"))

# ----------------------------
# REGISTRO · Editar/Excluir itens da lista
# ----------------------------
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
