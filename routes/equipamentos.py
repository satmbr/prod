from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine
from datetime import date
import json

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
    maquina_id = request.form.get("maquina_id")  # agora OBRIGATÓRIA para validar vínculo
    codigo = (request.form.get("codigo") or "").strip()
    unidade = (request.form.get("unidade") or "").strip()
    ativo = True if request.form.get("ativo") == "on" else False

    if not id_ or not maquina_id:
        return redirect(url_for("equipamentos.cadastro", msg="Selecione a máquina e o ponto para atualizar."))

    try:
        sets, params = [], {"id": id_, "maquina_id": maquina_id}
        if codigo:
            sets.append("codigo=:codigo"); params["codigo"] = codigo
        if unidade:
            sets.append("unidade=:unidade"); params["unidade"] = unidade
        sets.append("ativo=:ativo"); params["ativo"] = ativo

        if not sets:
            return redirect(url_for("equipamentos.cadastro", msg="Nada para atualizar."))

        with get_engine().begin() as conn:
            # garante que o ponto pertence à máquina selecionada
            result = conn.execute(
                text(f"UPDATE ponto_medicao SET {', '.join(sets)} WHERE id=:id AND maquina_id=:maquina_id"),
                params
            )
            if result.rowcount == 0:
                return redirect(url_for("equipamentos.cadastro",
                                        msg="Ponto não pertence à máquina selecionada ou não existe."))

        return redirect(url_for("equipamentos.cadastro", msg="Ponto atualizado."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao atualizar ponto: {e}"))

@bp.post("/cadastro/ponto/delete")
def ponto_delete():
    id_ = request.form.get("id")
    maquina_id = request.form.get("maquina_id")  # OBRIGATÓRIA
    if not id_ or not maquina_id:
        return redirect(url_for("equipamentos.cadastro", msg="Selecione a máquina e o ponto a excluir."))

    try:
        with get_engine().begin() as conn:
            # apaga somente se pertencer à máquina informada
            result = conn.execute(
                text("DELETE FROM ponto_medicao WHERE id=:id AND maquina_id=:maquina_id"),
                {"id": id_, "maquina_id": maquina_id}
            )
            if result.rowcount == 0:
                return redirect(url_for("equipamentos.cadastro",
                                        msg="Ponto não pertence à máquina selecionada ou não existe."))

        return redirect(url_for("equipamentos.cadastro", msg="Ponto excluído."))
    except Exception as e:
        return redirect(url_for("equipamentos.cadastro", msg=f"Erro ao excluir ponto: {e}"))

# ---------- helpers novos ----------
def _subnav(active: str):
    return [
        {"text": "Cadastro",   "href": url_for("equipamentos.cadastro"),   "active": active == "cadastro"},
        {"text": "PartDiaria", "href": url_for("equipamentos.partdiaria"), "active": active == "partdiaria"},
    ]

def _listas_basicas():
    with get_engine().connect() as conn:
        maquinas = conn.execute(text("""
            SELECT id, tag, descricao FROM maquina
            WHERE ativo = TRUE
            ORDER BY tag
        """)).mappings().all()
        atividades = conn.execute(text("""
            SELECT id, nome FROM atividade
            ORDER BY nome
        """)).mappings().all()
    return maquinas, atividades

# ---------- página PartDiaria ----------
@bp.get("/partdiaria")
def partdiaria():
    filtros = {
        "ini": request.args.get("ini"),
        "fim": request.args.get("fim"),
        "maq": request.args.get("maq"),
        "act": request.args.get("act"),
    }
    where = []
    params = {}
    if filtros["ini"]:
        where.append("pd.data >= :ini"); params["ini"] = filtros["ini"]
    if filtros["fim"]:
        where.append("pd.data <= :fim"); params["fim"] = filtros["fim"]
    if filtros["maq"]:
        where.append("pd.maquina_id = :maq"); params["maq"] = filtros["maq"]
    if filtros["act"]:
        where.append("pd.atividade_id = :act"); params["act"] = filtros["act"]
    wh = ("WHERE " + " AND ".join(where)) if where else ""

    with get_engine().connect() as conn:
        resultados = conn.execute(text(f"""
            SELECT pd.id, pd.data,
                   to_char(pd.hora_inicio, 'HH24:MI') AS hora_inicio,
                   to_char(pd.hora_fim, 'HH24:MI')    AS hora_fim,
                   pd.obs, pd.maquina_id, pd.atividade_id,
                   m.tag AS maquina_tag, m.descricao AS maquina_desc,
                   a.nome AS atividade_nome
            FROM parte_diaria pd
            JOIN maquina   m ON m.id = pd.maquina_id
            JOIN atividade a ON a.id = pd.atividade_id
            {wh}
            ORDER BY pd.data DESC, pd.hora_inicio ASC
            LIMIT 500
        """), params).mappings().all()

    maquinas, atividades = _listas_basicas()
    return render_template("equipamentos/partdiaria.html",
                           subnav_links=_subnav("partdiaria"),
                           filtros=filtros,
                           resultados=resultados,
                           maquinas=maquinas,
                           atividades=atividades,
                           today=date.today().isoformat(),
                           msg=request.args.get("msg"))

# ---------- CRUD Parte Diária ----------
@bp.post("/partdiaria/create")
def part_create():
    data = request.form.get("data")
    maquina_id = request.form.get("maquina_id")
    atividade_id = request.form.get("atividade_id")
    hora_inicio = request.form.get("hora_inicio")
    hora_fim = request.form.get("hora_fim")
    obs = request.form.get("obs")

    if not all([data, maquina_id, atividade_id, hora_inicio, hora_fim]):
        return redirect(url_for("equipamentos.partdiaria", msg="Preencha todos os campos obrigatórios."))

    if hora_inicio >= hora_fim:
        return redirect(url_for("equipamentos.partdiaria", msg="Hora inicial deve ser menor que a final."))

    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO parte_diaria (data, maquina_id, atividade_id, hora_inicio, hora_fim, obs)
                VALUES (:data, :maquina_id, :atividade_id, :hora_inicio, :hora_fim, :obs)
            """), dict(data=data, maquina_id=maquina_id, atividade_id=atividade_id,
                       hora_inicio=hora_inicio, hora_fim=hora_fim, obs=obs))
        return redirect(url_for("equipamentos.partdiaria", msg="Lançamento salvo."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao salvar: {e}"))
        
@bp.post("/partdiaria/create_lote")
def part_create_lote():
    raw = request.form.get("lancamentos_json", "").strip()

    if not raw:
        return redirect(url_for("equipamentos.partdiaria", msg="Nenhum lançamento foi enviado."))

    try:
        itens = json.loads(raw)
    except Exception:
        return redirect(url_for("equipamentos.partdiaria", msg="JSON de lançamentos inválido."))

    if not isinstance(itens, list) or not itens:
        return redirect(url_for("equipamentos.partdiaria", msg="Nenhum lançamento válido foi informado."))

    try:
        with get_engine().begin() as conn:
            for item in itens:
                data = (item.get("data") or "").strip()
                maquina_id = item.get("maquina_id")
                atividade_id = item.get("atividade_id")
                hora_inicio = (item.get("hora_inicio") or "").strip()
                hora_fim = (item.get("hora_fim") or "").strip()
                obs = (item.get("obs") or "").strip()

                if not data or not maquina_id or not atividade_id or not hora_inicio or not hora_fim:
                    continue

                conn.execute(text("""
                    INSERT INTO parte_diaria
                        (data, maquina_id, atividade_id, hora_inicio, hora_fim, obs)
                    VALUES
                        (:d, :m, :a, :hi, :hf, :obs)
                """), {
                    "d": data,
                    "m": maquina_id,
                    "a": atividade_id,
                    "hi": hora_inicio,
                    "hf": hora_fim,
                    "obs": obs
                })

        return redirect(url_for("equipamentos.partdiaria", msg="Lançamentos salvos com sucesso."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao salvar lote: {e}"))

@bp.post("/partdiaria/item/update")
def part_update():
    id_ = request.form.get("id")
    data = request.form.get("data")
    atividade_id = request.form.get("atividade_id")
    hora_inicio = request.form.get("hora_inicio")
    hora_fim = request.form.get("hora_fim")
    obs = request.form.get("obs")

    if not all([id_, data, atividade_id, hora_inicio, hora_fim]):
        return redirect(url_for("equipamentos.partdiaria", msg="Preencha os campos obrigatórios do item."))

    if hora_inicio >= hora_fim:
        return redirect(url_for("equipamentos.partdiaria", msg="Hora inicial deve ser menor que a final."))

    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE parte_diaria
                   SET data=:data,
                       atividade_id=:atividade_id,
                       hora_inicio=:hora_inicio,
                       hora_fim=:hora_fim,
                       obs=:obs
                 WHERE id=:id
            """), dict(id=id_, data=data, atividade_id=atividade_id,
                       hora_inicio=hora_inicio, hora_fim=hora_fim, obs=obs))
        return redirect(url_for("equipamentos.partdiaria", msg="Lançamento atualizado."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao atualizar: {e}"))

@bp.post("/partdiaria/item/delete")
def part_delete():
    id_ = request.form.get("id")
    if not id_:
        return redirect(url_for("equipamentos.partdiaria", msg="ID do lançamento não informado."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM parte_diaria WHERE id=:id"), {"id": id_})
        return redirect(url_for("equipamentos.partdiaria", msg="Lançamento excluído."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao excluir: {e}"))

# ---------- CRUD Atividade ----------
@bp.post("/atividade/create")
def act_create():
    nome = (request.form.get("nome") or "").strip()
    if not nome:
        return redirect(url_for("equipamentos.partdiaria", msg="Informe o nome da atividade."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO atividade (nome) VALUES (:n)"), {"n": nome})
        return redirect(url_for("equipamentos.partdiaria", msg="Atividade cadastrada."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao cadastrar atividade: {e}"))

@bp.post("/atividade/update")
def act_update():
    id_ = request.form.get("id")
    nome = (request.form.get("nome") or "").strip()
    if not id_:
        return redirect(url_for("equipamentos.partdiaria", msg="Selecione a atividade."))
    if not nome:
        return redirect(url_for("equipamentos.partdiaria", msg="Informe o novo nome."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE atividade SET nome=:n WHERE id=:id"), {"n": nome, "id": id_})
        return redirect(url_for("equipamentos.partdiaria", msg="Atividade atualizada."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao atualizar atividade: {e}"))

@bp.post("/atividade/delete")
def act_delete():
    id_ = request.form.get("id")
    if not id_:
        return redirect(url_for("equipamentos.partdiaria", msg="Selecione a atividade."))
    try:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM atividade WHERE id=:id"), {"id": id_})
        return redirect(url_for("equipamentos.partdiaria", msg="Atividade excluída."))
    except Exception as e:
        return redirect(url_for("equipamentos.partdiaria", msg=f"Erro ao excluir atividade: {e}"))
