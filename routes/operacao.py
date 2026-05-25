from datetime import date
import json
from flask import Blueprint, render_template, request, redirect, url_for, session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from routes.auth import login_required, permission_required
from db import get_engine

bp = Blueprint("operacao", __name__, url_prefix="/operacao")


# -------------------------------------------------------------------
# Helper: permissões do usuário logado
# -------------------------------------------------------------------
def user_can(chave: str) -> bool:
    permissoes = session.get("permissoes", [])
    return chave in permissoes or "auth:administrar" in permissoes


# -------------------------------------------------------------------
# Helper: sub-menu da Operação
# -------------------------------------------------------------------
def build_operacao_subnav(active: str | None):
    """
    Monta os links do sub-menu (Produção / Registro / Cadastro).
    'active' deve ser: 'producao', 'registro', 'cadastro' ou None.
    """
    links = []

    if user_can("operacao:visualizar"):
        links.append(
            {
                "text": "Produção",
                "href": url_for("operacao.producao"),
                "active": active == "producao",
            }
        )
        links.append(
            {
                "text": "Registro",
                "href": url_for("operacao.registro"),
                "active": active == "registro",
            }
        )

    if user_can("operacao:criar"):
        links.append(
            {
                "text": "Cadastro",
                "href": url_for("operacao.cadastro"),
                "active": active == "cadastro",
            }
        )

    return links


# -------------------------------------------------------------------
# Helper: carrega EH e Frentes (tabelas já usadas em Registro/Cadastro)
# -------------------------------------------------------------------
def load_eh_frentes(conn):
    eh_list = []
    fr_list = []

    try:
        eh_list = (
            conn.execute(
                text("SELECT id, eh FROM entre_house ORDER BY eh")
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError:
        eh_list = []

    try:
        fr_list = (
            conn.execute(
                text("SELECT id, frente FROM frente_equipe ORDER BY frente")
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError:
        fr_list = []

    return eh_list, fr_list


# -------------------------------------------------------------------
# /operacao/  -> tela “limpa” (só com o sub-menu)
# -------------------------------------------------------------------
@bp.route("/")
@login_required
@permission_required("operacao", "visualizar")
def index():
    subnav = build_operacao_subnav(None)
    return render_template(
        "operacao/index.html",
        subnav_links=subnav,
    )


# -------------------------------------------------------------------
# /operacao/producao
# -------------------------------------------------------------------
@bp.route("/producao")
@login_required
@permission_required("operacao", "visualizar")
def producao():
    engine = get_engine()

    with engine.connect() as conn:
        ehs = []
        try:
            ehs = (
                conn.execute(
                    text(
                        "SELECT id, eh AS nome "
                        "FROM entre_house "
                        "ORDER BY eh"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            ehs = []

        eh_id_param = request.args.get("eh_id")
        eh_id = int(eh_id_param) if eh_id_param else None

        if eh_id is None and ehs:
            eh_id = ehs[0]["id"]

        data_param = request.args.get("data_partdiaria")
        data_partdiaria = data_param if data_param else date.today().isoformat()

        # ------------------------------------------------------------------
        # BLOCO 1 – ACOMPANHAMENTO RENOVAÇÃO (01 - Renovação)
        # ------------------------------------------------------------------
        dados = []
        if eh_id is not None:
            try:
                sql_acomp = text(
                    """
                    WITH base AS (
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
        # BLOCO 2 – Parte Diária
        # ------------------------------------------------------------------
        dados_partdiaria = []
        grafico_atividades = {"labels": [], "tempos": []}

        try:
            sql_pd_p190 = text(
                """
                SELECT
                    a.nome AS atividade,
                    m.tag  AS tag,
                    pd.data,
                    to_char(pd.hora_inicio, 'HH24:MI') AS hora_inicio,
                    to_char(pd.hora_fim,   'HH24:MI') AS hora_fim,
                    EXTRACT(EPOCH FROM (pd.hora_fim - pd.hora_inicio)) / 60 AS duracao
                FROM parte_diaria pd
                JOIN maquina   m ON m.id = pd.maquina_id
                JOIN atividade a ON a.id = pd.atividade_id
                WHERE pd.data = :data_ref
                  AND m.tag = :tag_maquina
                ORDER BY pd.hora_inicio
                """
            )

            rows_pd = conn.execute(
                sql_pd_p190,
                {
                    "data_ref": data_partdiaria,
                    "tag_maquina": "P190-66001",
                }
            ).mappings().all()

            if not rows_pd:
                sql_pd_data = text(
                    """
                    SELECT
                        a.nome AS atividade,
                        m.tag  AS tag,
                        pd.data,
                        to_char(pd.hora_inicio, 'HH24:MI') AS hora_inicio,
                        to_char(pd.hora_fim,   'HH24:MI') AS hora_fim,
                        EXTRACT(EPOCH FROM (pd.hora_fim - pd.hora_inicio)) / 60 AS duracao
                    FROM parte_diaria pd
                    JOIN maquina   m ON m.id = pd.maquina_id
                    JOIN atividade a ON a.id = pd.atividade_id
                    WHERE pd.data = :data_ref
                    ORDER BY m.tag, pd.hora_inicio
                    """
                )

                rows_pd = conn.execute(
                    sql_pd_data,
                    {"data_ref": data_partdiaria}
                ).mappings().all()

            dados_partdiaria = list(rows_pd)

        except SQLAlchemyError:
            dados_partdiaria = []

        labels = [r["atividade"] for r in dados_partdiaria]
        tempos = [float(r["duracao"] or 0.0) for r in dados_partdiaria]
        grafico_atividades = {"labels": labels, "tempos": tempos}

        # ------------------------------------------------------------------
        # BLOCO 3 – Resumo frentes
        # ------------------------------------------------------------------
        dados_resumo_frentes = []
        try:
            sql_resumo = text(
                """
                WITH base AS (
                    SELECT
                        r.data::date AS data,
                        SUM(
                            CASE WHEN f.frente = '02 - Carregamento_novo'
                                 THEN r.realizado ELSE 0 END
                        ) AS carregado,
                        SUM(
                            CASE WHEN f.frente = '05 - Descarregamento_velho'
                                 THEN r.realizado ELSE 0 END
                        ) AS desc_velho,
                        SUM(
                            CASE WHEN f.frente = '07 - Descarregamento_novo'
                                 THEN r.realizado ELSE 0 END
                        ) AS desc_novo,
                        SUM(
                            CASE WHEN f.frente = '03 - Remoção_grampos'
                                 THEN r.realizado ELSE 0 END
                        ) AS rem_grampos,
                        SUM(
                            CASE WHEN f.frente = '04 - Remoção_galochas'
                                 THEN r.realizado ELSE 0 END
                        ) AS rem_galochas,
                        SUM(
                            CASE WHEN f.frente = '06 - Aplicação_grampos'
                                 THEN r.realizado ELSE 0 END
                        ) AS aplicado,
                        SUM(
                            CASE WHEN f.frente = '09 - Segregacao_velho'
                                 THEN r.realizado ELSE 0 END
                        ) AS seg_ruins,
                        SUM(
                            CASE WHEN f.frente = '08 - Segregacao_novo'
                                 THEN r.realizado ELSE 0 END
                        ) AS seg_bons
                    FROM producao_realizada r
                    JOIN frente_equipe f ON f.id = r.frente_id
                    WHERE r.eh_id = :eh_id
                    GROUP BY r.data
                )
                SELECT
                    data,
                    carregado,
                    0::float AS saldo,
                    SUM(carregado) OVER (ORDER BY data) AS acumulado_carregado,
                    desc_velho,
                    desc_novo,
                    rem_grampos,
                    rem_grampos AS fa_grampos,
                    SUM(rem_grampos) OVER (ORDER BY data) AS acum_rem_grampos,
                    rem_galochas,
                    rem_galochas AS fa_galochas,
                    SUM(rem_galochas) OVER (ORDER BY data) AS acum_rem_galochas,
                    aplicado,
                    0::float AS aberto,
                    seg_ruins,
                    seg_bons
                FROM base
                ORDER BY data
                """
            )

            dados_resumo_frentes = (
                conn.execute(sql_resumo, {"eh_id": eh_id})
                .mappings()
                .all()
            )
        except SQLAlchemyError:
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
@login_required
@permission_required("operacao", "criar")
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
@login_required
@permission_required("operacao", "criar")
def eh_create():
    eh = request.form.get("eh", "").strip()
    if not eh:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO entre_house (eh) VALUES (:eh)"),
            {"eh": eh}
        )

    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/eh/update", methods=["POST"])
@login_required
@permission_required("operacao", "editar")
def eh_update():
    eid = request.form.get("id")
    novo = request.form.get("novo_eh", "").strip()
    if not eid or not novo:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE entre_house SET eh = :novo WHERE id = :id"),
            {"novo": novo, "id": eid},
        )

    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/eh/delete", methods=["POST"])
@login_required
@permission_required("operacao", "excluir")
def eh_delete():
    eid = request.form.get("id")
    if not eid:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM entre_house WHERE id = :id"),
            {"id": eid}
        )

    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/frente/create", methods=["POST"])
@login_required
@permission_required("operacao", "criar")
def frente_create():
    frente = request.form.get("frente", "").strip()
    if not frente:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO frente_equipe (frente) VALUES (:fr)"),
            {"fr": frente},
        )

    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/frente/update", methods=["POST"])
@login_required
@permission_required("operacao", "editar")
def frente_update():
    fid = request.form.get("id")
    novo = request.form.get("nova_frente", "").strip()
    if not fid or not novo:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE frente_equipe SET frente = :novo WHERE id = :id"),
            {"novo": novo, "id": fid},
        )

    return redirect(url_for("operacao.cadastro"))


@bp.route("/cadastro/frente/delete", methods=["POST"])
@login_required
@permission_required("operacao", "excluir")
def frente_delete():
    fid = request.form.get("id")
    if not fid:
        return redirect(url_for("operacao.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM frente_equipe WHERE id = :id"),
            {"id": fid}
        )

    return redirect(url_for("operacao.cadastro"))


# -------------------------------------------------------------------
# /operacao/registro  (Planejado x Realizado)
# -------------------------------------------------------------------
def _numero_positivo(valor):
    """Converte textos vindos do formulário para número positivo."""
    if valor is None:
        return None

    txt = str(valor).strip().replace(".", "").replace(",", ".") if "," in str(valor) else str(valor).strip()

    if not txt:
        return None

    try:
        numero = float(txt)
    except (TypeError, ValueError):
        return None

    if numero < 0:
        return None

    return numero


def _upsert_producao(conn, tabela: str, campo: str, eh_id, frente_id, data_str, valor) -> str:
    """
    Salva um valor diário por EH + Frente + Data.

    Primeiro tenta atualizar um registro existente. Se não existir, insere.
    Isso evita erro quando já houver lançamento do mesmo dia e também permite
    corrigir o valor diário sem criar duplicidade no acompanhamento.
    """
    tabelas_permitidas = {
        "producao_realizada": "realizado",
        "producao_planejada": "planejado",
    }

    if tabela not in tabelas_permitidas or tabelas_permitidas[tabela] != campo:
        raise ValueError("Tabela/campo de produção inválido.")

    result = conn.execute(
        text(
            f"""
            UPDATE {tabela}
               SET {campo} = :val
             WHERE eh_id = :eh
               AND frente_id = :fr
               AND data = :dt
            """
        ),
        {"eh": eh_id, "fr": frente_id, "dt": data_str, "val": valor},
    )

    if result.rowcount and result.rowcount > 0:
        return "atualizado"

    conn.execute(
        text(
            f"""
            INSERT INTO {tabela} (eh_id, frente_id, data, {campo})
            VALUES (:eh, :fr, :dt, :val)
            """
        ),
        {"eh": eh_id, "fr": frente_id, "dt": data_str, "val": valor},
    )
    return "inserido"


def _redirect_registro(msg: str | None = None, keep_open: str | None = None):
    params = {}
    if msg:
        params["msg"] = msg
    if keep_open:
        params["keep_open"] = keep_open
    return redirect(url_for("operacao.registro", **params))


@bp.route("/registro", methods=["GET"])
@login_required
@permission_required("operacao", "visualizar")
def registro():
    engine = get_engine()

    with engine.connect() as conn:
        eh_list, fr_list = load_eh_frentes(conn)

        feh = request.args.get("feh") or None
        ffr = request.args.get("ffr") or None
        fdt = request.args.get("fdt") or None

        where = []
        params = {}

        if feh:
            where.append("e.id = :feh")
            params["feh"] = feh

        if ffr:
            where.append("f.id = :ffr")
            params["ffr"] = ffr

        if fdt:
            where.append("r.data = :fdt")
            params["fdt"] = fdt

        wh_rlz = "WHERE " + " AND ".join(where) if where else ""

        lista_rlz = (
            conn.execute(
                text(
                    f"""
                    SELECT
                        r.id,
                        r.data,
                        r.realizado,
                        e.eh       AS eh_nome,
                        f.frente   AS frente_nome
                    FROM producao_realizada r
                    JOIN entre_house e   ON e.id = r.eh_id
                    JOIN frente_equipe f ON f.id = r.frente_id
                    {wh_rlz}
                    ORDER BY r.data, e.eh, f.frente
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )

        where_pln = []
        params_pln = {}

        if feh:
            where_pln.append("e.id = :feh")
            params_pln["feh"] = feh

        if ffr:
            where_pln.append("f.id = :ffr")
            params_pln["ffr"] = ffr

        if fdt:
            where_pln.append("p.data = :fdt")
            params_pln["fdt"] = fdt

        wh_pln = "WHERE " + " AND ".join(where_pln) if where_pln else ""

        lista_pln = (
            conn.execute(
                text(
                    f"""
                    SELECT
                        p.id,
                        p.data,
                        p.planejado,
                        e.eh       AS eh_nome,
                        f.frente   AS frente_nome
                    FROM producao_planejada p
                    JOIN entre_house e   ON e.id = p.eh_id
                    JOIN frente_equipe f ON f.id = p.frente_id
                    {wh_pln}
                    ORDER BY p.data, e.eh, f.frente
                    """
                ),
                params_pln,
            )
            .mappings()
            .all()
        )

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
        today=date.today().isoformat(),
        keep_open=request.args.get("keep_open"),
        msg=request.args.get("msg"),
    )


@bp.route("/registro/realizada/create", methods=["POST"])
@login_required
@permission_required("operacao", "criar")
def registro_realizada_create():
    eh_id = request.form.get("eh_id")
    fr_id = request.form.get("frente_id")
    data_str = request.form.get("data")
    realizado = _numero_positivo(request.form.get("realizado"))

    if not (eh_id and fr_id and data_str and realizado is not None):
        return _redirect_registro("Preencha EH, Frente, Data e Executado.", "realizada")

    try:
        engine = get_engine()
        with engine.begin() as conn:
            status = _upsert_producao(
                conn,
                "producao_realizada",
                "realizado",
                eh_id,
                fr_id,
                data_str,
                realizado,
            )

        msg = "Registro executado salvo." if status == "inserido" else "Registro executado atualizado."
        return _redirect_registro(msg, "realizada")
    except Exception as e:
        return _redirect_registro(f"Erro ao salvar executado: {e}", "realizada")


@bp.route("/registro/realizada/create_lote", methods=["POST"])
@login_required
@permission_required("operacao", "criar")
def registro_realizada_create_lote():
    raw = (request.form.get("lancamentos_json") or "").strip()

    if not raw:
        return _redirect_registro("Nenhum lançamento executado foi enviado.", "realizada")

    try:
        itens = json.loads(raw)
    except Exception:
        return _redirect_registro("Lista de executados inválida. Recarregue a página e tente novamente.", "realizada")

    if not isinstance(itens, list) or not itens:
        return _redirect_registro("Nenhum lançamento executado válido foi informado.", "realizada")

    salvos = 0
    inseridos = 0
    atualizados = 0

    try:
        engine = get_engine()
        with engine.begin() as conn:
            for item in itens:
                if not isinstance(item, dict):
                    continue

                eh_id = item.get("eh_id")
                fr_id = item.get("frente_id")
                data_str = (item.get("data") or "").strip()
                realizado = _numero_positivo(item.get("realizado"))

                if not (eh_id and fr_id and data_str and realizado is not None):
                    continue

                status = _upsert_producao(
                    conn,
                    "producao_realizada",
                    "realizado",
                    eh_id,
                    fr_id,
                    data_str,
                    realizado,
                )
                salvos += 1
                if status == "inserido":
                    inseridos += 1
                else:
                    atualizados += 1

        if salvos == 0:
            return _redirect_registro("Nenhum lançamento executado válido foi salvo.", "realizada")

        detalhes = []
        if inseridos:
            detalhes.append(f"{inseridos} novo(s)")
        if atualizados:
            detalhes.append(f"{atualizados} atualizado(s)")

        msg = f"{salvos} lançamento(s) executado(s) salvo(s) com sucesso"
        if detalhes:
            msg += f" ({', '.join(detalhes)})"
        msg += "."

        return _redirect_registro(msg, "realizada")
    except Exception as e:
        return _redirect_registro(f"Erro ao salvar executados em lote: {e}", "realizada")


@bp.route("/registro/realizada/delete", methods=["POST"])
@login_required
@permission_required("operacao", "excluir")
def registro_realizada_delete():
    rid = request.form.get("id")
    if not rid:
        return _redirect_registro("Registro executado não informado.", "realizada")

    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM producao_realizada WHERE id = :id"),
                {"id": rid},
            )
        return _redirect_registro("Registro executado excluído.", "realizada")
    except Exception as e:
        return _redirect_registro(f"Erro ao excluir executado: {e}", "realizada")


@bp.route("/registro/planejada/create", methods=["POST"])
@login_required
@permission_required("operacao", "criar")
def registro_planejada_create():
    eh_id = request.form.get("eh_id")
    fr_id = request.form.get("frente_id")
    data_str = request.form.get("data")
    planejado = _numero_positivo(request.form.get("planejado"))

    if not (eh_id and fr_id and data_str and planejado is not None):
        return _redirect_registro("Preencha EH, Frente, Data e Planejado.", "planejada")

    try:
        engine = get_engine()
        with engine.begin() as conn:
            status = _upsert_producao(
                conn,
                "producao_planejada",
                "planejado",
                eh_id,
                fr_id,
                data_str,
                planejado,
            )

        msg = "Registro planejado salvo." if status == "inserido" else "Registro planejado atualizado."
        return _redirect_registro(msg, "planejada")
    except Exception as e:
        return _redirect_registro(f"Erro ao salvar planejado: {e}", "planejada")


@bp.route("/registro/planejada/create_lote", methods=["POST"])
@login_required
@permission_required("operacao", "criar")
def registro_planejada_create_lote():
    raw = (request.form.get("lancamentos_json") or "").strip()

    if not raw:
        return _redirect_registro("Nenhum lançamento planejado foi enviado.", "planejada")

    try:
        itens = json.loads(raw)
    except Exception:
        return _redirect_registro("Lista de planejados inválida. Recarregue a página e tente novamente.", "planejada")

    if not isinstance(itens, list) or not itens:
        return _redirect_registro("Nenhum lançamento planejado válido foi informado.", "planejada")

    salvos = 0
    inseridos = 0
    atualizados = 0

    try:
        engine = get_engine()
        with engine.begin() as conn:
            for item in itens:
                if not isinstance(item, dict):
                    continue

                eh_id = item.get("eh_id")
                fr_id = item.get("frente_id")
                data_str = (item.get("data") or "").strip()
                planejado = _numero_positivo(item.get("planejado"))

                if not (eh_id and fr_id and data_str and planejado is not None):
                    continue

                status = _upsert_producao(
                    conn,
                    "producao_planejada",
                    "planejado",
                    eh_id,
                    fr_id,
                    data_str,
                    planejado,
                )
                salvos += 1
                if status == "inserido":
                    inseridos += 1
                else:
                    atualizados += 1

        if salvos == 0:
            return _redirect_registro("Nenhum lançamento planejado válido foi salvo.", "planejada")

        detalhes = []
        if inseridos:
            detalhes.append(f"{inseridos} novo(s)")
        if atualizados:
            detalhes.append(f"{atualizados} atualizado(s)")

        msg = f"{salvos} lançamento(s) planejado(s) salvo(s) com sucesso"
        if detalhes:
            msg += f" ({', '.join(detalhes)})"
        msg += "."

        return _redirect_registro(msg, "planejada")
    except Exception as e:
        return _redirect_registro(f"Erro ao salvar planejados em lote: {e}", "planejada")


@bp.route("/registro/planejada/delete", methods=["POST"])
@login_required
@permission_required("operacao", "excluir")
def registro_planejada_delete():
    pid = request.form.get("id")
    if not pid:
        return _redirect_registro("Registro planejado não informado.", "planejada")

    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM producao_planejada WHERE id = :id"),
                {"id": pid},
            )
        return _redirect_registro("Registro planejado excluído.", "planejada")
    except Exception as e:
        return _redirect_registro(f"Erro ao excluir planejado: {e}", "planejada")

