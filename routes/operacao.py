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
    Tela de Produção resumida para a nova estrutura/layout.
    Mostra:
      - tabela + gráfico de acompanhamento da frente principal (renovação)
      - resumo da PartDiaria da renovadora P190-66001
      - tabela consolidada de frentes 02/03/04...
      - gráficos frente 02 (barras + 'bateria')
      - gauges percentuais por frente
    """

    # Filtros básicos (seguindo sua lógica original)
    sel_eh = request.args.get("eh") or request.args.get("eh_id")  # id entre_house
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
        # BLOCO 1 — ACOMPANHAMENTO (frente principal)
        # ============================================================
        dados_renovacao = []
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
                )
                SELECT
                    dias.d                              AS data,
                    COALESCE(pl.planejado, 0)::float    AS previsto_dia,
                    COALESCE(rl.realizado, 0)::float    AS realizado_dia,
                    SUM(COALESCE(pl.planejado, 0)) OVER (ORDER BY dias.d)::float   AS previsto_total,
                    SUM(COALESCE(rl.realizado, 0)) OVER (ORDER BY dias.d)::float   AS realizado_total,
                    (
                        SUM(COALESCE(rl.realizado, 0)) OVER (ORDER BY dias.d)
                      - SUM(COALESCE(pl.planejado, 0)) OVER (ORDER BY dias.d)
                    )::float AS diferenca,
                    (
                        SUM(COALESCE(pl.planejado, 0)) OVER (ORDER BY dias.d)
                      - SUM(COALESCE(rl.realizado, 0)) OVER (ORDER BY dias.d)
                    )::float AS atraso
                FROM dias
                LEFT JOIN pl ON pl.data = dias.d
                LEFT JOIN rl ON rl.data = dias.d
                ORDER BY dias.d
            """)
            dados_renovacao = conn.execute(
                sql_acomp,
                {"dini": start_month, "dfim": sel_dt_obj, "eh": sel_eh, "fr": sel_fr},
            ).mappings().all()

        # ============================================================
        # BLOCO 2 — PART DIÁRIA P190-66001
        # ============================================================
        dados_partdiaria = []
        grafico_atividades = None
        if sel_dt_pd:
            from sqlalchemy import text  # (garanta que este import já está no topo do arquivo)

            # ...

            sql_pd = text("""
                SELECT
                    a.nome AS atividade,
                    to_char(pd.hora_inicio, 'HH24:MI') AS hora_inicio,
                    to_char(pd.hora_fim,   'HH24:MI')  AS hora_fim,
                    EXTRACT(EPOCH FROM (pd.hora_fim - pd.hora_inicio)) / 60 AS duracao
                FROM parte_diaria pd
                JOIN maquina   m ON m.id = pd.maquina_id
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.data = :data_pd
                  AND m.tag   = 'P190-66001'
                ORDER BY pd.hora_inicio
            """)

            try:
                dados_partdiaria = conn.execute(
                    sql_pd, {"data_pd": sel_dt_pd}
                ).mappings().all()
            except Exception:
                # Se a tabela ainda não existir no Postgres, não quebra a página
                dados_partdiaria = []

            # para gráfico: labels e tempos em minutos
            labels_pd = [r["atividade"] for r in dados_partdiaria]
            tempos_pd = [float(r["duracao"] or 0) for r in dados_partdiaria]
            grafico_atividades = {
                "labels": labels_pd,
                "tempos": tempos_pd,
            }

        # ============================================================
        # BLOCO 3 — RESUMO FRENTES (Carregamento, Remoção, Pregação etc.)
        # ============================================================
        dados_resumo_frentes = []
        grafico_barra_carregamento = []
        grafico_bateria_carregamento = {}

        if sel_eh:
            # base de frentes: exemplo genérico, adapte aos campos reais da tabela producao_frentes
            fr_sql = text("""
                WITH base AS (
                    SELECT
                        data::date AS data,
                        COALESCE(carregado, 0)      AS r1,
                        COALESCE(saldo, 0)          AS r2,
                        COALESCE(rem_grampos, 0)    AS r3,
                        COALESCE(rem_galochas, 0)   AS r4,
                        COALESCE(aplicado, 0)       AS r6,
                        COALESCE(seg_ruins, 0)      AS r7,
                        COALESCE(seg_bons, 0)       AS r8,
                        COALESCE(desc_velho, 0)     AS desc_v,
                        COALESCE(desc_novo, 0)      AS desc_n
                    FROM producao_frentes
                    WHERE eh_id = :eh
                )
                SELECT
                    data,
                    r1::float                       AS carregado,
                    (r1 - r2)::float                AS saldo,
                    (SUM(r1) OVER (ORDER BY data))::float AS acumulado_carregado,
                    desc_v::float                   AS desc_velho,
                    desc_n::float                   AS desc_novo,
                    r3::float                       AS rem_grampos,
                    (r3 - r2)::float                AS fa_grampos,
                    (SUM(r3) OVER (ORDER BY data))::float AS acum_rem_grampos,
                    r4::float                       AS rem_galochas,
                    (r4 - r2)::float                AS fa_galochas,
                    (SUM(r4) OVER (ORDER BY data))::float AS acum_rem_galochas,
                    r6::float                       AS aplicado,
                    (SUM(r1) OVER (ORDER BY data) - SUM(r6) OVER (ORDER BY data))::float AS frente_aplicado,
                    (SUM(r6) OVER (ORDER BY data))::float AS acum_aplicado,
                    r7::float                       AS seg_ruins,
                    r8::float                       AS seg_bons
                FROM base
                ORDER BY data
            """)
            frentes_rows = conn.execute(fr_sql, {"eh": sel_eh}).mappings().all()
            dados_resumo_frentes = frentes_rows

            # Frente 02 – assumindo que no seu modelo o "carregado" seja a frente 02
            grafico_barra_carregamento = [
                {
                    "data": str(r["data"]),
                    "planejado": float(r["carregado"] or 0),
                    "executado": float(r["aplicado"] or 0),
                    "acumulado_planejado": float(r["acumulado_carregado"] or 0),
                    "acumulado_executado": float(r["acum_aplicado"] or 0),
                }
                for r in frentes_rows
            ]

            # Bateria – usa o total planejado (soma carregado) e acumulados até a data filtrada
            total_planejado = sum(float(r["carregado"] or 0) for r in frentes_rows)
            acumulado_planejado = sum(
                float(r["carregado"] or 0)
                for r in frentes_rows
                if r["data"] <= sel_dt_obj
            )
            acumulado_executado = sum(
                float(r["aplicado"] or 0)
                for r in frentes_rows
                if r["data"] <= sel_dt_obj
            )
            grafico_bateria_carregamento = {
                "planejado_total": total_planejado,
                "planejado_acumulado": acumulado_planejado,
                "executado_acumulado": acumulado_executado,
            }

        # ============================================================
        # BLOCO 4 — DESCARGA & SEGREGAÇÃO (intervalo próprio)
        # ============================================================
        dsd_rows = []
        if sel_eh and dsd_i and dsd_f:
            sql_dsd = text("""
                SELECT *
                FROM descarga_segregacao
                WHERE eh_id = :eh
                  AND data BETWEEN :di AND :df
                ORDER BY data
            """)
            dsd_rows = conn.execute(
                sql_dsd,
                {"eh": sel_eh, "di": dsd_i, "df": dsd_f},
            ).mappings().all()

        # ============================================================
        # BLOCO 5 — Percentuais para Gauges (uma ideia simplificada)
        # ============================================================
        percentuais_graficos = {}
        if sel_eh:
            # Exemplo didático: calcula percentuais "executado / planejado" por frente.
            sql_pct = text("""
                SELECT
                    f.id,
                    f.frente,
                    COALESCE(SUM(p.realizado), 0) AS realizado,
                    COALESCE(SUM(pl.planejado), 0) AS planejado
                FROM frente_equipe f
                LEFT JOIN producao_realizada p
                  ON p.frente_id = f.id AND p.eh_id = :eh
                LEFT JOIN producao_planejada pl
                  ON pl.frente_id = f.id AND pl.eh_id = :eh
                GROUP BY f.id, f.frente
                ORDER BY f.frente
            """)
            rows_pct = conn.execute(sql_pct, {"eh": sel_eh}).mappings().all()
            for idx, r in enumerate(rows_pct, start=1):
                pla = float(r["planejado"] or 0)
                exe = float(r["realizado"] or 0)
                if pla <= 0:
                    pct = 0.0
                else:
                    pct = min((exe / pla) * 100.0, 999.9)
                # aqui só um exemplo de ícone e título
                percentuais_graficos[f"frente_{r['id']}"] = {
                    "titulo": r["frente"],
                    "percentual_executado": pct,
                    "icone": f"frente{idx}.png",  # ex.: frente1.png, frente2.png etc.
                }

    return render_template(
        "operacao/producao.html",
        subnav_links=_subnav("producao"),
        ehs=eh_list,
        frentes=fr_list,
        maquinas=maq_list,
        sel_eh=sel_eh,
        sel_fr=sel_fr,
        sel_dt=sel_dt,
        sel_maq=sel_maq,
        sel_dt_pd=sel_dt_pd,
        dsd_i=dsd_i,
        dsd_f=dsd_f,
        dados=dados_renovacao,
        dados_partdiaria=dados_partdiaria,
        grafico_atividades=grafico_atividades,
        dados_resumo_frentes=dados_resumo_frentes,
        grafico_barra_carregamento=grafico_barra_carregamento,
        grafico_bateria_carregamento=grafico_bateria_carregamento,
        dsd_rows=dsd_rows,
        percentuais_graficos=percentuais_graficos,
        data_partdiaria=sel_dt_pd,
    )


# ----------------------------------------------------------------
# CADASTRO – EH e FRENTE
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


# ========================= EH =========================
@bp.post("/cadastro/eh/create")
def eh_create():
    eh = (request.form.get("eh") or "").strip()
    if not eh:
        return redirect(url_for("operacao.cadastro", msg="Informe a EH."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO entre_house (eh) VALUES (:eh)"),
                         {"eh": eh})
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


# ========================= FRENTE =========================
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
# REGISTRO – Planejado / Executado
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

        # Monta WHERE dinâmico
        where_rlz_sql = ("WHERE " + " AND ".join(where_rlz)) if where_rlz else ""
        where_pln_sql = ("WHERE " + " AND ".join(where_pln)) if where_pln else ""

        sql_realizada = text(f"""
            SELECT
                r.id,
                r.data,
                r.realizado,
                e.eh          AS eh_nome,
                f.frente      AS frente_nome
            FROM producao_realizada r
            JOIN entre_house    e ON e.id = r.eh_id
            JOIN frente_equipe  f ON f.id = r.frente_id
            {where_rlz_sql}
            ORDER BY r.data DESC, e.eh, f.frente
        """)

        sql_planejada = text(f"""
            SELECT
                p.id,
                p.data,
                p.planejado,
                e.eh          AS eh_nome,
                f.frente      AS frente_nome
            FROM producao_planejada p
            JOIN entre_house    e ON e.id = p.eh_id
            JOIN frente_equipe  f ON f.id = p.frente_id
            {where_pln_sql}
            ORDER BY p.data DESC, e.eh, f.frente
        """)

        lista_rlz = conn.execute(sql_realizada, params).mappings().all()
        lista_pln = conn.execute(sql_planejada, params).mappings().all()

    return render_template(
        "operacao/registro.html",
        subnav_links=_subnav("registro"),
        eh_list=eh_list,
        fr_list=fr_list,
        lista_rlz=lista_rlz,
        lista_pln=lista_pln,
        feh=feh,
        ffr=ffr,
        fdt=fdt,
        keep_open=keep_open,
        msg=request.args.get("msg"),
    )


@bp.post("/registro/realizada")
def registro_realizada_create():
    eh_id = request.form.get("eh_id")
    frente_id = request.form.get("frente_id")
    data_str = request.form.get("data")
    realizado = request.form.get("realizado")

    if not (eh_id and frente_id and data_str and realizado):
        return redirect(url_for("operacao.registro", open="realizada", msg="Preencha todos os campos."))

    with get_engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO producao_realizada (eh_id, frente_id, data, realizado)
                VALUES (:eh, :fr, :dt, :rz)
            """),
            {
                "eh": eh_id,
                "fr": frente_id,
                "dt": data_str,
                "rz": realizado,
            },
        )

    return redirect(url_for("operacao.registro", open="realizada", msg="Registro executado salvo."))


@bp.post("/registro/planejada")
def registro_planejada_create():
    eh_id = request.form.get("eh_id")
    frente_id = request.form.get("frente_id")
    data_str = request.form.get("data")
    planejado = request.form.get("planejado")

    if not (eh_id and frente_id and data_str and planejado):
        return redirect(url_for("operacao.registro", open="planejada", msg="Preencha todos os campos."))

    with get_engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO producao_planejada (eh_id, frente_id, data, planejado)
                VALUES (:eh, :fr, :dt, :pl)
            """),
            {
                "eh": eh_id,
                "fr": frente_id,
                "dt": data_str,
                "pl": planejado,
            },
        )

    return redirect(url_for("operacao.registro", open="planejada", msg="Registro planejado salvo."))


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
