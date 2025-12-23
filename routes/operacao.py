from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("operacao", __name__, url_prefix="/operacao")


# -------------------------------------------------------------------
# Helper: sub-menu da Operação
# -------------------------------------------------------------------
def build_operacao_subnav(active: str | None):
    """
    Monta os links do sub-menu (Produção / Registro / Cadastro).
    'active' deve ser: 'producao', 'registro', 'cadastro' ou None.
    """
    return [
        {
            "text": "Produção",
            "href": url_for("operacao.producao"),
            "active": active == "producao",
        },
        {
            "text": "Registro",
            "href": url_for("operacao.registro"),
            "active": active == "registro",
        },
        {
            "text": "Cadastro",
            "href": url_for("operacao.cadastro"),
            "active": active == "cadastro",
        },
    ]


# -------------------------------------------------------------------
# Helper: carrega EH e Frentes (tabelas já usadas em Registro/Cadastro)
# -------------------------------------------------------------------
def load_eh_frentes(conn):
    eh_list = []
    fr_list = []

    # Tabela de EH: entre_house (id, eh)
    try:
        eh_list = conn.execute(
            text("SELECT id, eh FROM entre_house ORDER BY eh")
        ).mappings().all()
    except SQLAlchemyError:
        eh_list = []

    # Tabela de Frentes: frente_equipe (id, frente)
    try:
        fr_list = conn.execute(
            text("SELECT id, frente FROM frente_equipe ORDER BY frente")
        ).mappings().all()
    except SQLAlchemyError:
        fr_list = []

    return eh_list, fr_list


# -------------------------------------------------------------------
# /operacao/  -> tela “limpa” (só com o sub-menu)
# -------------------------------------------------------------------
@bp.route("/")
def index():
    # sub-menu, mas sem nada no corpo da página
    subnav = build_operacao_subnav(None)
    return render_template(
        "operacao/index.html",
        subnav_links=subnav,
    )


# -------------------------------------------------------------------
# /operacao/producao
# -------------------------------------------------------------------
@bp.route("/producao")
def producao():
    engine = get_engine()
    with engine.connect() as conn:
        # 1) Carregar EH a partir de entre_house
        ehs = []
        try:
            ehs = conn.execute(
                text("SELECT id, eh AS nome FROM entre_house ORDER BY eh")
            ).mappings().all()
        except SQLAlchemyError:
            ehs = []

        # EH selecionada
        eh_id_param = request.args.get("eh_id")
        eh_id = int(eh_id_param) if eh_id_param else None

        if eh_id is None and ehs:
            eh_id = ehs[0]["id"]

        # Data selecionada (para destacar linha, filtros etc.)
        data_param = request.args.get("data_partdiaria")
        if data_param:
            data_partdiaria = data_param
        else:
            data_partdiaria = date.today().isoformat()

        # ------------------------------------------------------------------
        # BLOCO 1 – ACOMPANHAMENTO RENOVAÇÃO (01 - Renovação)
        # usando producao_planejada / producao_realizada
        # ------------------------------------------------------------------
        dados = []
        if eh_id is not None:
            try:
                sql_acomp = text(
                    """
                    WITH base AS (
                        -- Planejado dia
                        SELECT
                            p.data::date AS data,
                            SUM(p.planejado)::float AS previsto_dia,
                            0.0::float AS realizado_dia
                        FROM producao_planejada p
                        JOIN frente_equipe f ON f.id = p.frente_id
                        WHERE p.eh_id = :eh_id
                          AND f.frente = '01 - Renovação'
                        GROUP BY p.data

                        UNION ALL

                        -- Realizado dia
                        SELECT
                            r.data::date AS data,
                            0.0::float AS previsto_dia,
                            SUM(r.realizado)::float AS realizado_dia
                        FROM producao_realizada r
                        JOIN frente_equipe f ON f.id = r.frente_id
                        WHERE r.eh_id = :eh_id
                          AND f.frente = '01 - Renovação'
                        GROUP BY r.data
                    )
                    SELECT
                        data,
                        SUM(previsto_dia) AS previsto_dia,
                        SUM(SUM(previsto_dia)) OVER (ORDER BY data) AS previsto_total,
                        SUM(realizado_dia) AS realizado_dia,
                        SUM(SUM(realizado_dia)) OVER (ORDER BY data) AS realizado_total
                    FROM base
                    GROUP BY data
                    ORDER BY data
                    """
                )

                rows = conn.execute(sql_acomp, {"eh_id": eh_id}).mappings().all()
                acumulado_prev = 0.0
                acumulado_real = 0.0

                for r in rows:
                    previsto_dia = float(r["previsto_dia"] or 0.0)
                    realizado_dia = float(r["realizado_dia"] or 0.0)
                    acumulado_prev += previsto_dia
                    acumulado_real += realizado_dia
                    dif = acumulado_real - acumulado_prev
                    atraso = dif / 850.0 if 850 else 0.0

                    dados.append(
                        {
                            "data": r["data"].isoformat(),
                            "previsto_dia": previsto_dia,
                            "previsto_total": acumulado_prev,
                            "realizado_dia": realizado_dia,
                            "realizado_total": acumulado_real,
                            "diferenca": round(dif, 2),
                            "atraso": round(atraso, 2),
                        }
                    )
            except SQLAlchemyError:
                dados = []

        # ------------------------------------------------------------------
        # BLOCO 2 – Parte Diária (ainda sem tabela 'part_diaria' no Postgres)
        # Deixamos vazio para não quebrar a página.
        # ------------------------------------------------------------------
        dados_partdiaria = []
        grafico_atividades = {"labels": [], "tempos": []}

        # ------------------------------------------------------------------
        # BLOCO 3 – Resumo frentes / gráficos frente 02 / gauges
        # Por enquanto, sem consultas específicas -> listas vazias.
        # (quando tiver as tabelas prontas, a gente preenche aqui)
        # ------------------------------------------------------------------
        dados_resumo_frentes = []
        grafico_barra_carregamento = []
        grafico_bateria_carregamento = {}
        percentuais_graficos = {}

    subnav = build_operacao_subnav("producao")

    return render_template(
        "operacao/producao.html",
        subnav_links=subnav,
        ehs=ehs,
        eh_id=eh_id,
        data_partdiaria=data_partdiaria,
        dados=dados,
        dados_partdiaria=dados_partdiaria,
        dados_resumo_frentes=dados_resumo_frentes,
        grafico_atividades=grafico_atividades,
        grafico_barra_carregamento=grafico_barra_carregamento,
        grafico_bateria_carregamento=grafico_bateria_carregamento,
        percentuais_graficos=percentuais_graficos,
    )


# -------------------------------------------------------------------
# /operacao/cadastro  (EH e Frentes)
# -------------------------------------------------------------------
@bp.route("/cadastro", methods=["GET"])
def cadastro():
    engine = get_engine()
    with engine.connect() as conn:
        lista_eh, lista_frente = load_eh_frentes(conn)

    subnav = build_operacao_subnav("cadastro")
    return render_template(
        "operacao/cadastro.html",
        subnav_links=subnav,
        lista_eh=lista_eh,
        lista_frente=lista_frente,
        msg=None,
    )


@bp.route("/cadastro/eh/create", methods=["POST"])
def eh_create():
    eh = request.form.get("eh", "").strip()
    if not eh:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO entre_house (eh) VALUES (:eh)"), {"eh": eh}
        )
        conn.commit()
    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/eh/update", methods=["POST"])
def eh_update():
    eid = request.form.get("id")
    novo = request.form.get("novo_eh", "").strip()
    if not eid or not novo:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE entre_house SET eh = :novo WHERE id = :id"),
            {"novo": novo, "id": eid},
        )
        conn.commit()
    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/eh/delete", methods=["POST"])
def eh_delete():
    eid = request.form.get("id")
    if not eid:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM entre_house WHERE id = :id"), {"id": eid}
        )
        conn.commit()
    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/frente/create", methods=["POST"])
def frente_create():
    frente = request.form.get("frente", "").strip()
    if not frente:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO frente_equipe (frente) VALUES (:fr)"),
            {"fr": frente},
        )
        conn.commit()
    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/frente/update", methods=["POST"])
def frente_update():
    fid = request.form.get("id")
    novo = request.form.get("nova_frente", "").strip()
    if not fid or not novo:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE frente_equipe SET frente = :novo WHERE id = :id"),
            {"novo": novo, "id": fid},
        )
        conn.commit()
    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/frente/delete", methods=["POST"])
def frente_delete():
    fid = request.form.get("id")
    if not fid:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM frente_equipe WHERE id = :id"), {"id": fid}
        )
        conn.commit()
    return redirect(url_for("operacao.cadastro"))


# -------------------------------------------------------------------
# /operacao/registro  (Planejado x Realizado)
# -------------------------------------------------------------------
@bp.route("/registro", methods=["GET"])
def registro():
    engine = get_engine()
    with engine.connect() as conn:
        eh_list, fr_list = load_eh_frentes(conn)

        feh = request.args.get("feh") or None
        ffr = request.args.get("ffr") or None
        fdt = request.args.get("fdt") or None

        # Lista de realizados
        lista_rlz = conn.execute(
            text(
                """
                SELECT
                    r.id,
                    r.data,
                    r.realizado,
                    e.eh       AS eh_nome,
                    f.frente   AS frente_nome
                FROM producao_realizada r
                JOIN entre_house e   ON e.id = r.eh_id
                JOIN frente_equipe f ON f.id = r.frente_id
                ORDER BY r.data, e.eh, f.frente
                """
            )
        ).mappings().all()

        # Lista de planejados
        lista_pln = conn.execute(
            text(
                """
                SELECT
                    p.id,
                    p.data,
                    p.planejado,
                    e.eh       AS eh_nome,
                    f.frente   AS frente_nome
                FROM producao_planejada p
                JOIN entre_house e   ON e.id = p.eh_id
                JOIN frente_equipe f ON f.id = p.frente_id
                ORDER BY p.data, e.eh, f.frente
                """
            )
        ).mappings().all()

    subnav = build_operacao_subnav("registro")
    return render_template(
        "operacao/registro.html",
        subnav_links=subnav,
        eh_list=eh_list,
        fr_list=fr_list,
        lista_rlz=lista_rlz,
        lista_pln=lista_pln,
        feh=feh,
        ffr=ffr,
        fdt=fdt,
        keep_open=None,
        msg=None,
    )


@bp.route("/registro/realizada/create", methods=["POST"])
def registro_realizada_create():
    eh_id = request.form.get("eh_id")
    fr_id = request.form.get("frente_id")
    data_str = request.form.get("data")
    realizado = request.form.get("realizado")

    if not (eh_id and fr_id and data_str and realizado):
        return redirect(url_for("operacao.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO producao_realizada (eh_id, frente_id, data, realizado)
                VALUES (:eh, :fr, :dt, :val)
                """
            ),
            {"eh": eh_id, "fr": fr_id, "dt": data_str, "val": realizado},
        )
        conn.commit()

    return redirect(url_for("operacao.registro", keep_open="realizada"))


@bp.route("/registro/realizada/delete", methods=["POST"])
def registro_realizada_delete():
    rid = request.form.get("id")
    if not rid:
        return redirect(url_for("operacao.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM producao_realizada WHERE id = :id"), {"id": rid}
        )
        conn.commit()

    return redirect(url_for("operacao.registro", keep_open="realizada"))


@bp.route("/registro/planejada/create", methods=["POST"])
def registro_planejada_create():
    eh_id = request.form.get("eh_id")
    fr_id = request.form.get("frente_id")
    data_str = request.form.get("data")
    planejado = request.form.get("planejado")

    if not (eh_id and fr_id and data_str and planejado):
        return redirect(url_for("operacao.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO producao_planejada (eh_id, frente_id, data, planejado)
                VALUES (:eh, :fr, :dt, :val)
                """
            ),
            {"eh": eh_id, "fr": fr_id, "dt": data_str, "val": planejado},
        )
        conn.commit()

    return redirect(url_for("operacao.registro", keep_open="planejada"))


@bp.route("/registro/planejada/delete", methods=["POST"])
def registro_planejada_delete():
    pid = request.form.get("id")
    if not pid:
        return redirect(url_for("operacao.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM producao_planejada WHERE id = :id"), {"id": pid}
        )
        conn.commit()

    return redirect(url_for("operacao.registro", keep_open="planejada"))
