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
    """Tela Operação · Produção (Acompanhamento, PartDiária, Frentes, Descarga & Segregação)."""
    from datetime import date, datetime

    # -------- filtros do topo --------
    sel_eh = request.args.get("eh")                # id entre_house
    sel_fr = request.args.get("fr")                # id frente_equipe
    sel_dt = request.args.get("dt") or date.today().isoformat()
    sel_dt_obj = date.fromisoformat(sel_dt)

    sel_maq   = request.args.get("maq")            # id máquina
    sel_dt_pd = request.args.get("dt_pd") or sel_dt

    # Intervalo específico para "Descarga & Segregação"
    dsd_i = request.args.get("dsd_ini")
    dsd_f = request.args.get("dsd_fim")

    # começo do mês para gerar a série diária (evita usar ::cast no SQL)
    start_month = sel_dt_obj.replace(day=1)

    with get_engine().connect() as conn:
        # -------- listas para selects --------
        eh_list = conn.execute(text(
            "SELECT id, eh FROM entre_house ORDER BY eh"
        )).mappings().all()

        fr_list = conn.execute(text(
            "SELECT id, frente FROM frente_equipe ORDER BY frente"
        )).mappings().all()

        maq_list = conn.execute(text("""
            SELECT id, tag, descricao
            FROM maquina
            WHERE ativo IS TRUE
            ORDER BY tag
        """)).mappings().all()

        # ============================================================
        # BLOCO 1 — ACOMPANHAMENTO (por EH + Frente, mês até a data)
        # ============================================================
        prod_rows = []
        chart_prod = {"labels": [], "prev_dia": [], "real_dia": [], "prev_tot": [], "real_tot": []}

        if sel_eh and sel_fr:
            sql_acomp = text("""
                WITH dias AS (
                    SELECT gs::date AS d
                    FROM generate_series(:dini, :dfim, interval '1 day') gs
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
                       previsto_dia::float AS previsto_dia,
                       SUM(previsto_dia) OVER (ORDER BY data)::float AS previsto_total,
                       realizado_dia::float AS realizado_dia,
                       SUM(realizado_dia) OVER (ORDER BY data)::float AS realizado_total
                FROM base
                ORDER BY data
            """)
            params_acomp = {
                "eh": sel_eh,
                "fr": sel_fr,
                "dini": start_month,
                "dfim": sel_dt_obj,
            }
            prod = conn.execute(sql_acomp, params_acomp).mappings().all()

            for r in prod:
                # dif = realizado_total - previsto_total ; atraso = dif / 850
                dif = float((r["realizado_total"] or 0.0) - (r["previsto_total"] or 0.0))
                atraso = (dif / 850.0) if 850 else 0.0
                prod_rows.append({
                    "data": r["data"],
                    "previsto_dia": float(r["previsto_dia"] or 0.0),
                    "previsto_total": float(r["previsto_total"] or 0.0),
                    "realizado_dia": float(r["realizado_dia"] or 0.0),
                    "realizado_total": float(r["realizado_total"] or 0.0),
                    "dif": dif,
                    "atraso": atraso,
                    "is_sel_day": (r["data"] == sel_dt_obj),
                })
                chart_prod["labels"].append(r["data"].strftime("%d/%m"))
                chart_prod["prev_dia"].append(float(r["previsto_dia"] or 0.0))
                chart_prod["real_dia"].append(float(r["realizado_dia"] or 0.0))
                chart_prod["prev_tot"].append(float(r["previsto_total"] or 0.0))
                chart_prod["real_tot"].append(float(r["realizado_total"] or 0.0))

        # ============================================================
        # BLOCO 2 — PARTE DIÁRIA (por máquina + dia)
        # ============================================================
        # ===================== BLOCO 2 — PARTE DIÁRIA =====================
        pd_lista = []
        pd_graf  = {"labels": [], "horas": [], "minutos": []}  # minutos para o template

        if sel_maq and sel_dt_pd:
            sql_pd = text("""
                SELECT pd.id,
                       a.nome AS evento,
                       to_char(pd.hora_inicio, 'HH24:MI') AS inicio,
                       to_char(pd.hora_fim, 'HH24:MI')    AS fim,
                       EXTRACT(EPOCH FROM (pd.hora_fim - pd.hora_inicio))/3600.0 AS horas_dec
                FROM parte_diaria pd
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.maquina_id = :maq
                  AND pd.data = :d
                ORDER BY pd.hora_inicio
            """)
            pd_lista = conn.execute(sql_pd, {"maq": sel_maq, "d": sel_dt_pd}).mappings().all()

            sql_pd_agg = text("""
                SELECT a.nome AS evento,
                       ROUND(EXTRACT(EPOCH FROM SUM(pd.hora_fim - pd.hora_inicio))/3600.0, 4) AS horas_dec
                FROM parte_diaria pd
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.maquina_id = :maq
                  AND pd.data = :d
                GROUP BY a.nome
                ORDER BY horas_dec DESC
            """)
            for r in conn.execute(sql_pd_agg, {"maq": sel_maq, "d": sel_dt_pd}).mappings():
                h = float(r["horas_dec"] or 0.0)
                pd_graf["labels"].append(r["evento"])
                pd_graf["horas"].append(h)
                pd_graf["minutos"].append(int(round(h * 60)))

        # ============================================================
        # BLOCO 3 — FRENTES (por EH, dia a dia)
        # ============================================================
        frentes_rows = []
        if sel_eh:
            fr_sql = text("""
                WITH datas AS (
                    SELECT DISTINCT data::date AS d
                    FROM producao_realizada
                    WHERE eh_id = :eh AND frente_id IN (1,2,3,4,6)
                ),
                f1 AS ( SELECT data::date d, SUM(realizado) r1 FROM producao_realizada WHERE eh_id=:eh AND frente_id=1 GROUP BY data::date ),
                f2 AS ( SELECT data::date d, SUM(realizado) r2 FROM producao_realizada WHERE eh_id=:eh AND frente_id=2 GROUP BY data::date ),
                f3 AS ( SELECT data::date d, SUM(realizado) r3 FROM producao_realizada WHERE eh_id=:eh AND frente_id=3 GROUP BY data::date ),
                f4 AS ( SELECT data::date d, SUM(realizado) r4 FROM producao_realizada WHERE eh_id=:eh AND frente_id=4 GROUP BY data::date ),
                f6 AS ( SELECT data::date d, SUM(realizado) r6 FROM producao_realizada WHERE eh_id=:eh AND frente_id=6 GROUP BY data::date ),
                base AS (
                    SELECT d.d AS data,
                           COALESCE(f1.r1,0) AS r1,
                           COALESCE(f2.r2,0) AS r2,
                           COALESCE(f3.r3,0) AS r3,
                           COALESCE(f4.r4,0) AS r4,
                           COALESCE(f6.r6,0) AS r6
                    FROM datas d
                    LEFT JOIN f1 ON f1.d=d.d
                    LEFT JOIN f2 ON f2.d=d.d
                    LEFT JOIN f3 ON f3.d=d.d
                    LEFT JOIN f4 ON f4.d=d.d
                    LEFT JOIN f6 ON f6.d=d.d
                )
                SELECT
                   data,
                   r2::float                                           AS carregado,
                   (SUM(r2) OVER (ORDER BY data) - SUM(r1) OVER (ORDER BY data))::float AS saldo,
                   (SUM(r2) OVER (ORDER BY data))::float              AS acum_carregado,

                   r3::float                                           AS rem_grampos,
                   (SUM(r3) OVER (ORDER BY data) - SUM(r1) OVER (ORDER BY data))::float AS frente_grampos,
                   (SUM(r3) OVER (ORDER BY data))::float              AS acum_grampos,

                   r4::float                                           AS rem_galochas,
                   (SUM(r4) OVER (ORDER BY data) - SUM(r1) OVER (ORDER BY data))::float AS frente_galochas,
                   (SUM(r4) OVER (ORDER BY data))::float              AS acum_galochas,

                   r6::float                                           AS aplicado,
                   (SUM(r1) OVER (ORDER BY data) - SUM(r6) OVER (ORDER BY data))::float AS frente_aplicado,
                   (SUM(r6) OVER (ORDER BY data))::float              AS acum_aplicado
                FROM base
                ORDER BY data
            """)
            frentes_rows = conn.execute(fr_sql, {"eh": sel_eh}).mappings().all()

        # ============================================================
        # BLOCO 4 — DESCARGA & SEGREGAÇÃO (intervalo próprio)
        # ============================================================
        dsd_rows = []
        if sel_eh and dsd_i and dsd_f:
            dsd_sql = text("""
                WITH rng AS (
                    SELECT gs::date AS d
                    FROM generate_series(:di::date, :df::date, interval '1 day') gs
                ),
                e AS (SELECT id, eh FROM entre_house WHERE id=:eh),
                f5 AS ( SELECT data::date d, SUM(realizado) r5 FROM producao_realizada WHERE eh_id=:eh AND frente_id=5 AND data BETWEEN :di AND :df GROUP BY data::date ),
                f7 AS ( SELECT data::date d, SUM(realizado) r7 FROM producao_realizada WHERE eh_id=:eh AND frente_id=7 AND data BETWEEN :di AND :df GROUP BY data::date ),
                f8 AS ( SELECT data::date d, SUM(realizado) r8 FROM producao_realizada WHERE eh_id=:eh AND frente_id=8 AND data BETWEEN :di AND :df GROUP BY data::date ),
                f9 AS ( SELECT data::date d, SUM(realizado) r9 FROM producao_realizada WHERE eh_id=:eh AND frente_id=9 AND data BETWEEN :di AND :df GROUP BY data::date ),
                base AS (
                    SELECT r.d AS data,
                           COALESCE(f7.r7,0) AS r7,
                           COALESCE(f5.r5,0) AS r5,
                           COALESCE(f8.r8,0) AS r8,
                           COALESCE(f9.r9,0) AS r9
                    FROM rng r
                    LEFT JOIN f7 ON f7.d=r.d
                    LEFT JOIN f5 ON f5.d=r.d
                    LEFT JOIN f8 ON f8.d=r.d
                    LEFT JOIN f9 ON f9.d=r.d
                )
                SELECT
                   b.data,
                   (b.r7)::float AS novo,
                   (SUM(b.r7) OVER (ORDER BY b.data))::float AS acum_novo,
                   (b.r5)::float AS velho,
                   (SUM(b.r5) OVER (ORDER BY b.data))::float AS acum_velho,
                   (b.r8)::float AS seg_novo,
                   (SUM(b.r8) OVER (ORDER BY b.data))::float AS acum_seg_novo,
                   (b.r9)::float AS seg_velho,
                   (SUM(b.r9) OVER (ORDER BY b.data))::float AS acum_seg_velho,
                   e.eh AS eh_nome
                FROM base b CROSS JOIN e
                ORDER BY b.data
            """)
            dsd_rows = conn.execute(dsd_sql, {"eh": sel_eh, "di": dsd_i, "df": dsd_f}).mappings().all()

    # -------- render --------
    return render_template(
        "operacao/producao.html",
        subnav_links=_clean_nav(_subnav("producao")),
        # selects
        eh_list=eh_list, fr_list=fr_list, maq_list=maq_list,
        # valores selecionados
        sel_eh=sel_eh, sel_fr=sel_fr, sel_dt=sel_dt,
        sel_maq=sel_maq, sel_dt_pd=sel_dt_pd,
        dsd_ini=dsd_i, dsd_fim=dsd_f,
        # blocos
        prod_rows=prod_rows, chart_prod=chart_prod,
        pd_lista=pd_lista, pd_graf=pd_graf,
        frentes_rows=frentes_rows,
        dsd_rows=dsd_rows,
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
    fdt = request.args.get("fdt")  # filtro opcional por dia (YYYY-MM-DD)

    with get_engine().connect() as conn:
        eh_list = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr_list = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()

        # Filtros (constroem cláusulas diferentes para cada alias)
        params = {}
        where_rlz, where_pln = [], []

        if feh:
            where_rlz.append("r.eh_id = :feh")
            where_pln.append("p.eh_id = :feh")
            params["feh"] = feh

        if ffr:
            where_rlz.append("r.frente_id = :ffr")
            where_pln.append("p.frente_id = :ffr")
            params["ffr"] = ffr

        if fdt:
            where_rlz.append("r.data = :fdt")
            where_pln.append("p.data = :fdt")
            params["fdt"] = fdt

        where_sql_rlz = ("WHERE " + " AND ".join(where_rlz)) if where_rlz else ""
        where_sql_pln = ("WHERE " + " AND ".join(where_pln)) if where_pln else ""
        limit_sql = "" if (feh or ffr or fdt) else "LIMIT 30"

        # Executado (Realizada) com nomes
        sql_rlz = text(f"""
            SELECT
                r.id,
                r.data,
                r.eh_id,
                r.frente_id,
                e.eh       AS eh_nome,
                f.frente   AS frente_nome,
                r.realizado AS realizado
            FROM producao_realizada r
            JOIN entre_house   e ON e.id = r.eh_id
            JOIN frente_equipe f ON f.id = r.frente_id
            {where_sql_rlz}
            ORDER BY r.data DESC, e.eh, f.frente, r.id DESC
            {limit_sql}
        """)

        # Planejado com nomes
        sql_pln = text(f"""
            SELECT
                p.id,
                p.data,
                p.eh_id,
                p.frente_id,
                e.eh       AS eh_nome,
                f.frente   AS frente_nome,
                p.planejado AS planejado
            FROM producao_planejada p
            JOIN entre_house   e ON e.id = p.eh_id
            JOIN frente_equipe f ON f.id = p.frente_id
            {where_sql_pln}
            ORDER BY p.data DESC, e.eh, f.frente, p.id DESC
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
        keep_open=keep_open,  # mantém container aberto após salvar
        msg=request.args.get("msg")
    )

@bp.post("/registro/realizada")
def registro_realizada_create():
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

    # 👉 sem filtros na URL
    return redirect(url_for("operacao.registro", open="realizada", msg="Registro salvo!"))

@bp.post("/registro/planejada")
def registro_planejada_create():
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

    # 👉 sem filtros na URL
    return redirect(url_for("operacao.registro", open="planejada", msg="Registro salvo!"))

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
