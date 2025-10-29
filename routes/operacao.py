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

# remove itens None
def _clean_nav(nav):
    return [n for n in nav if n]

def _fetch_listas():
    """Carrega listas de EH e Frentes para selects."""
    with get_engine().connect() as conn:
        eh = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()
    return eh, fr

# ----------------------------
# GET raiz Operação
# ----------------------------
@bp.get("/")
def index():
    return render_template("operacao/index.html", subnav_links=_subnav(""))

# ----------------------------------------------------------------
# PRODUÇÃO
# ----------------------------------------------------------------
@bp.get("/producao")
def producao():
    """Tela de acompanhamento de produção + parte diária (2 contêineres)."""
    sel_eh = request.args.get("eh")      # id da entre_house
    sel_fr = request.args.get("fr")      # id da frente_equipe
    sel_dt = request.args.get("dt") or date.today().isoformat()
    sel_dt_obj = date.fromisoformat(sel_dt)  # evita usar ::date no SQL

    sel_maq   = request.args.get("maq")   # para parte diária
    sel_dt_pd = request.args.get("dt_pd") or sel_dt

    with get_engine().connect() as conn:
        # listas para selects
        eh_list = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr_list = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()
        # Se sua tabela 'maquina' não tiver 'ativo', remova o WHERE
        maq_list = conn.execute(text("""
            SELECT id, tag, descricao
            FROM maquina
            ORDER BY tag
        """)).mappings().all()

        # ===================== BLOCO 1: PRODUÇÃO =====================
        prod_rows = []
        chart_prod = {"labels": [], "prev_dia": [], "real_dia": [], "prev_tot": [], "real_tot": []}

        if sel_eh and sel_fr:
            sql = text("""
                WITH dias AS (
                    SELECT gs::date AS d
                    FROM generate_series(
                        date_trunc('month', :refdt),
                        :refdt,
                        interval '1 day'
                    ) gs
                ),
                pl AS (
                    SELECT data::date AS data, SUM(planejado) AS planejado
                    FROM producao_planejada
                    WHERE eh_id = :eh AND frente_id = :fr
                    GROUP BY data::date
                ),
                rl AS (
                    SELECT data::date AS data, SUM(realizado) AS realizado
                    FROM producao_realizada
                    WHERE eh_id = :eh AND frente_id = :fr
                    GROUP BY data::date
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
            params = {"eh": sel_eh, "fr": sel_fr, "refdt": sel_dt_obj}
            prod = conn.execute(sql, params).mappings().all()

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
                chart_prod["labels"].append(r["data"].strftime("%d/%m"))
                chart_prod["prev_dia"].append(float(r["previsto_dia"]))
                chart_prod["real_dia"].append(float(r["realizado_dia"]))
                chart_prod["prev_tot"].append(float(r["previsto_total"]))
                chart_prod["real_tot"].append(float(r["realizado_total"]))

        # ===================== BLOCO 2: PARTE DIÁRIA =====================
        pd_lista = []
        pd_graf  = {"labels": [], "horas": []}
        if sel_maq and sel_dt_pd:
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
        msg=request.args.get("msg"),
    )

# ----------------------------------------------------------------
# CADASTRO (EH / FRENTE)
# ----------------------------------------------------------------
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

# EH
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

# FRENTE
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

# ----------------------------------------------------------------
# REGISTRO (Executado / Planejado) — NOVO FLUXO
# ----------------------------------------------------------------

@bp.get("/registro")
def registro():
    """Tela de Registro com dois segmentos (Executado e Planejado).
       Ambos iniciam fechados; após salvar, mantemos o segmento aberto via ?open=..."""
    keep_open = request.args.get("open")  # "realizada" | "planejada" | None
    feh = request.args.get("feh")
    ffr = request.args.get("ffr")
    fdt = request.args.get("fdt")  # opcional filtro por dia (YYYY-MM-DD)

    with get_engine().connect() as conn:
        eh_list = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr_list = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()

        # Listagens (últimos 30 ou filtrados)
        params = {}
        where = []
        if feh:
            where.append("eh_id = :feh")
            params["feh"] = feh
        if ffr:
            where.append("frente_id = :ffr")
            params["ffr"] = ffr
        if fdt:
            where.append("data = :fdt")
            params["fdt"] = fdt

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        limit_sql = "" if where else "LIMIT 30"

        sql_rlz = text(f"""
            SELECT id, data, eh_id, frente_id, realizado
            FROM producao_realizada
            {where_sql}
            ORDER BY data DESC, id DESC
            {limit_sql}
        """)
        sql_pln = text(f"""
            SELECT id, data, eh_id, frente_id, planejado
            FROM producao_planejada
            {where_sql}
            ORDER BY data DESC, id DESC
            {limit_sql}
        """)
        lista_rlz = conn.execute(sql_rlz, params).mappings().all()
        lista_pln = conn.execute(sql_pln, params).mappings().all()

    return render_template(
        "operacao/registro.html",
        subnav_links=_clean_nav(_subnav("registro")),
        eh_list=eh_list, fr_list=fr_list,
        lista_rlz=lista_rlz, lista_pln=lista_pln,
        feh=feh, ffr=ffr, fdt=fdt,
        keep_open=keep_open,  # para manter container aberto após salvar
        msg=request.args.get("msg")
    )


@bp.post("/registro/realizada")
def registro_realizada_create():
    """Salvar Executado (Realizada) — upsert por (data, eh, frente). Mantém aberto após salvar."""
    form = request.form
    eh_id = form.get("eh_id")
    fr_id = form.get("frente_id")
    data_ = form.get("data")
    valor = form.get("realizado")

    if not (eh_id and fr_id and data_ and valor):
        return redirect(url_for("operacao.registro", open="realizada", msg="Preencha todos os campos!"))

    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO producao_realizada (data, realizado, eh_id, frente_id)
            VALUES (:data, :valor, :eh, :fr)
            ON CONFLICT (data, eh_id, frente_id)
            DO UPDATE SET realizado = EXCLUDED.realizado
        """), {"data": data_, "valor": int(valor), "eh": eh_id, "fr": fr_id})

    return redirect(url_for("operacao.registro", open="realizada", feh=eh_id, ffr=fr_id, fdt=data_, msg="Registro salvo!"))


@bp.post("/registro/planejada")
def registro_planejada_create():
    """Salvar Planejado — upsert por (data, eh, frente). Mantém aberto após salvar."""
    form = request.form
    eh_id = form.get("eh_id")
    fr_id = form.get("frente_id")
    data_ = form.get("data")
    valor = form.get("planejado")

    if not (eh_id and fr_id and data_ and valor):
        return redirect(url_for("operacao.registro", open="planejada", msg="Preencha todos os campos!"))

    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO producao_planejada (data, planejado, eh_id, frente_id)
            VALUES (:data, :valor, :eh, :fr)
            ON CONFLICT (data, eh_id, frente_id)
            DO UPDATE SET planejado = EXCLUDED.planejado
        """), {"data": data_, "valor": int(valor), "eh": eh_id, "fr": fr_id})

    return redirect(url_for("operacao.registro", open="planejada", feh=eh_id, ffr=fr_id, fdt=data_, msg="Registro salvo!"))


@bp.post("/registro/realizada/delete")
def registro_realizada_delete():
    rid = request.form.get("id")
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM producao_realizada WHERE id=:id"), {"id": rid})
    return redirect(url_for("operacao.registro", open="realizada", msg="Registro executado excluído."))


@bp.post("/registro/planejada/delete")
def registro_planejada_delete():
    pid = request.form.get("id")
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM producao_planejada WHERE id=:id"), {"id": pid})
    return redirect(url_for("operacao.registro", open="planejada", msg="Registro planejado excluído."))
