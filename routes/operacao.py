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
    """
    Produção com:
      - Filtros fixos (EH, Frente, Data, Máquina) + aplicar/limpar
      - Acompanhamento (tabela+gráfico) — inicia fechado
      - PartDiária (tabela+gráfico HH:MM) — inicia fechado
      - Frentes (tabela) — inicia fechado
      - Descarga e Segregação de Dormentes (intervalo data) — inicia fechado
    """
    from datetime import date, datetime, time

    # -------- Filtros do topo (sempre visíveis) --------
    sel_eh   = request.args.get("eh")       # id entre_house
    sel_fr   = request.args.get("fr")       # id frente_equipe
    sel_dt   = request.args.get("dt") or date.today().isoformat()
    sel_maq  = request.args.get("maq")      # id máquina (PD)
    # filtros exclusivos do bloco “Descarga/Segregação”
    dsd_i    = request.args.get("dsd_ini")
    dsd_f    = request.args.get("dsd_fim")

    # datas como objetos (evita ::date no SQL)
    sel_dt_obj = date.fromisoformat(sel_dt)

    with get_engine().connect() as conn:
        # Listas (selects)
        eh_list  = conn.execute(text("SELECT id, eh FROM entre_house ORDER BY eh")).mappings().all()
        fr_list  = conn.execute(text("SELECT id, frente FROM frente_equipe ORDER BY frente")).mappings().all()
        maq_list = conn.execute(text("""
            SELECT id, tag, descricao
            FROM maquina
            WHERE ativo IS TRUE
            ORDER BY tag
        """)).mappings().all()

        # ===================== BLOCO 1: ACOMPANHAMENTO =====================
        # Mostra todos os dias que têm registro (planejado ou realizado) para a EH+Frente.
        prod_rows  = []
        chart_prod = {"labels": [], "prev_dia": [], "real_dia": [], "prev_tot": [], "real_tot": []}

        if sel_eh and sel_fr:
            sql = text("""
                WITH datas AS (
                   SELECT DISTINCT data::date AS d
                   FROM producao_planejada WHERE eh_id=:eh AND frente_id=:fr
                   UNION
                   SELECT DISTINCT data::date AS d
                   FROM producao_realizada WHERE eh_id=:eh AND frente_id=:fr
                ),
                pl AS (
                   SELECT data::date AS data, SUM(planejado) AS planejado
                   FROM producao_planejada
                   WHERE eh_id=:eh AND frente_id=:fr
                   GROUP BY data::date
                ),
                rl AS (
                   SELECT data::date AS data, SUM(realizado) AS realizado
                   FROM producao_realizada
                   WHERE eh_id=:eh AND frente_id=:fr
                   GROUP BY data::date
                ),
                base AS (
                   SELECT d.d AS data,
                          COALESCE(pl.planejado, 0) AS previsto_dia,
                          COALESCE(rl.realizado, 0) AS realizado_dia
                   FROM datas d
                   LEFT JOIN pl ON pl.data=d.d
                   LEFT JOIN rl ON rl.data=d.d
                )
                SELECT data,
                       previsto_dia,
                       SUM(previsto_dia) OVER (ORDER BY data)  AS previsto_total,
                       realizado_dia,
                       SUM(realizado_dia) OVER (ORDER BY data) AS realizado_total
                FROM base
                ORDER BY data
            """)
            rows = conn.execute(sql, {"eh": sel_eh, "fr": sel_fr}).mappings().all()

            for r in rows:
                prev_tot = float(r["previsto_total"] or 0)
                real_tot = float(r["realizado_total"] or 0)
                dif      = real_tot - prev_tot
                atraso   = (dif / 850.0) if 850 else 0.0  # referência passada
                prod_rows.append({
                    "data": r["data"],
                    "previsto_dia": float(r["previsto_dia"] or 0),
                    "previsto_total": prev_tot,
                    "realizado_dia": float(r["realizado_dia"] or 0),
                    "realizado_total": real_tot,
                    "dif": dif,
                    "atraso": atraso,
                    "is_sel_day": (r["data"] == sel_dt_obj),
                })
                chart_prod["labels"].append(r["data"].strftime("%d/%m"))
                chart_prod["prev_dia"].append(float(r["previsto_dia"] or 0))
                chart_prod["real_dia"].append(float(r["realizado_dia"] or 0))
                chart_prod["prev_tot"].append(prev_tot)
                chart_prod["real_tot"].append(real_tot)

        # ===================== BLOCO 2: PART DIÁRIA =====================
        # tabela do dia + gráfico de horas por atividade (HH:MM)
        pd_lista = []
        pd_graf  = {"labels": [], "minutos": []}  # guardamos minutos; formatamos HH:MM no front

        if sel_maq and sel_dt:
            pd_sql = text("""
                SELECT pd.id,
                       a.nome AS evento,
                       to_char(pd.hora_inicio, 'HH24:MI') AS inicio,
                       to_char(pd.hora_fim, 'HH24:MI')    AS fim,
                       EXTRACT(EPOCH FROM (pd.hora_fim - pd.hora_inicio)) / 60.0 AS minutos
                FROM parte_diaria pd
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.maquina_id = :maq
                  AND pd.data = :d
                ORDER BY pd.hora_inicio
            """)
            pd_lista = conn.execute(pd_sql, {"maq": sel_maq, "d": sel_dt_obj}).mappings().all()

            # agregado por atividade para o gráfico
            agg = conn.execute(text("""
                SELECT a.nome AS evento,
                       EXTRACT(EPOCH FROM SUM(pd.hora_fim - pd.hora_inicio)) / 60.0 AS minutos
                FROM parte_diaria pd
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.maquina_id=:maq AND pd.data=:d
                GROUP BY a.nome
                ORDER BY 1
            """), {"maq": sel_maq, "d": sel_dt_obj}).mappings().all()

            for r in agg:
                pd_graf["labels"].append(r["evento"])
                pd_graf["minutos"].append(float(r["minutos"] or 0.0))

# ===================== BLOCO 3: FRENTES =====================
frentes_rows = []
if sel_eh:
    fr_sql = text("""
        WITH datas AS (
            SELECT DISTINCT data::date AS d
            FROM producao_realizada
            WHERE eh_id = :eh AND frente_id IN (1,2,3,4,6)
        ),
        f1 AS ( -- 01 - Renovação
            SELECT data::date AS d, SUM(realizado) AS r1
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=1
            GROUP BY data::date
        ),
        f2 AS ( -- 02 - Carregamento_novo
            SELECT data::date AS d, SUM(realizado) AS r2
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=2
            GROUP BY data::date
        ),
        f3 AS ( -- 03 - Remoção_grampos
            SELECT data::date AS d, SUM(realizado) AS r3
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=3
            GROUP BY data::date
        ),
        f4 AS ( -- 04 - Remoção_galochas
            SELECT data::date AS d, SUM(realizado) AS r4
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=4
            GROUP BY data::date
        ),
        f6 AS ( -- 06 - Aplicação_grampos
            SELECT data::date AS d, SUM(realizado) AS r6
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=6
            GROUP BY data::date
        ),
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
           r2::float                AS carregado,
           (SUM(r2) OVER (ORDER BY data) - SUM(r1) OVER (ORDER BY data))::float AS saldo,
           (SUM(r2) OVER (ORDER BY data))::float  AS acum_carregado,

           r3::float                AS rem_grampos,
           (SUM(r3) OVER (ORDER BY data) - SUM(r1) OVER (ORDER BY data))::float AS frente_grampos,
           (SUM(r3) OVER (ORDER BY data))::float  AS acum_grampos,

           r4::float                AS rem_galochas,
           (SUM(r4) OVER (ORDER BY data) - SUM(r1) OVER (ORDER BY data))::float AS frente_galochas,
           (SUM(r4) OVER (ORDER BY data))::float  AS acum_galochas,

           r6::float                AS aplicado,
           (SUM(r1) OVER (ORDER BY data) - SUM(r6) OVER (ORDER BY data))::float AS frente_aplicado,
           (SUM(r6) OVER (ORDER BY data))::float  AS acum_aplicado
        FROM base
        ORDER BY data
    """)
    frentes_rows = conn.execute(fr_sql, {"eh": sel_eh}).mappings().all()

# ===================== BLOCO 4: DESCARGA & SEGREGAÇÃO =====================
dsd_rows = []
if sel_eh and dsd_i and dsd_f:
    dsd_sql = text("""
        WITH rng AS (
            SELECT gs::date AS d
            FROM generate_series(:di::date, :df::date, interval '1 day') gs
        ),
        e AS (SELECT id, eh FROM entre_house WHERE id=:eh),
        f5 AS ( -- 05 - Descarregamento_velho
            SELECT data::date AS d, SUM(realizado) AS r5
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=5 AND data BETWEEN :di AND :df
            GROUP BY data::date
        ),
        f7 AS ( -- 07 - Descarregamento_novo
            SELECT data::date AS d, SUM(realizado) AS r7
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=7 AND data BETWEEN :di AND :df
            GROUP BY data::date
        ),
        f8 AS ( -- 08 - Segregacao_novo
            SELECT data::date AS d, SUM(realizado) AS r8
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=8 AND data BETWEEN :di AND :df
            GROUP BY data::date
        ),
        f9 AS ( -- 09 - Segregacao_velho
            SELECT data::date AS d, SUM(realizado) AS r9
            FROM producao_realizada
            WHERE eh_id=:eh AND frente_id=9 AND data BETWEEN :di AND :df
            GROUP BY data::date
        ),
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
    dsd_rows = conn.execute(
        dsd_sql, {"eh": sel_eh, "di": dsd_i, "df": dsd_f}
    ).mappings().all()

    return render_template(
        "operacao/producao.html",
        subnav_links=_clean_nav(_subnav("producao")),
        # selects
        eh_list=eh_list, fr_list=fr_list, maq_list=maq_list,
        # filtros atuais
        sel_eh=sel_eh, sel_fr=sel_fr, sel_dt=sel_dt,
        sel_maq=sel_maq, dsd_i=dsd_i, dsd_f=dsd_f,
        # dados
        prod_rows=prod_rows, chart_prod=chart_prod,
        pd_lista=pd_lista, pd_graf=pd_graf,
        frentes_rows=frentes_rows,
        dsd_rows=dsd_rows,
        # mensagem
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
