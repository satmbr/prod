# routes/colaboradores.py

from flask import Blueprint, render_template, request, redirect, url_for
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# -------------------------------------------------------------------
# Submenu do módulo Colaboradores
# -------------------------------------------------------------------
def build_colab_subnav(active: str | None):
    """
    Monta os links do sub-menu (Registro, depois virão outros).
    'active' pode ser: 'registro' ou None.
    """
    return [
        {
            "text": "Registro",
            "href": url_for("colaboradores.registro"),
            "active": active == "registro",
        },
        # futuros itens, tipo "Escalas", "Funções", etc.
    ]


# -------------------------------------------------------------------
# /colaboradores/  -> tela “limpa” só com título e sub-menu
# -------------------------------------------------------------------
@bp.route("/")
def index():
    subnav = build_colab_subnav(None)
    return render_template(
        "colaboradores/index.html",
        subnav_links=subnav,
    )


# -------------------------------------------------------------------
# /colaboradores/registro  -> cadastro + listagem
# -------------------------------------------------------------------
@bp.route("/registro", methods=["GET", "POST"])
def registro():
    engine = get_engine()
    msg = None

    with engine.connect() as conn:
        # --------------------- GRAVAÇÃO (POST) ----------------------
        if request.method == "POST":
            form = request.form

            nome = form.get("nome", "").strip()
            matricula = form.get("matricula", "").strip()

            # campos opcionais
            cpf = form.get("cpf", "").strip()
            rg = form.get("rg", "").strip()
            cnh = form.get("cnh", "").strip()
            ctps = form.get("ctps", "").strip()
            pis = form.get("pis", "").strip()
            data_nascimento = form.get("data_nascimento") or None
            funcao = form.get("funcao", "").strip()
            data_admissao = form.get("data_admissao") or None
            data_funcao = form.get("data_funcao") or None
            situacao_folha = form.get("situacao_folha", "").strip()
            mao_obra = form.get("mao_obra", "").strip()
            escala = form.get("escala", "").strip()
            horario_inicio = form.get("horario_inicio") or None
            horario_fim = form.get("horario_fim") or None
            inicio_ferias = form.get("inicio_ferias") or None
            fim_ferias = form.get("fim_ferias") or None
            nome_mae = form.get("nome_mae", "").strip()
            nome_pai = form.get("nome_pai", "").strip()
            cidade_nascimento = form.get("cidade_nascimento", "").strip()
            endereco = form.get("endereco", "").strip()
            cep = form.get("cep", "").strip()
            estado_civil = form.get("estado_civil", "").strip()
            salario = form.get("salario") or None
            contrato = form.get("contrato", "").strip()
            vencimento_cnh = form.get("vencimento_cnh") or None
            escolaridade = form.get("escolaridade", "").strip()

            if not nome or not matricula:
                msg = "Nome e matrícula são obrigatórios."
            else:
                try:
                    sql_insert = text(
                        """
                        INSERT INTO colaborador (
                            nome,
                            matricula,
                            cpf,
                            rg,
                            cnh,
                            ctps,
                            pis,
                            data_nascimento,
                            funcao,
                            data_admissao,
                            data_funcao,
                            situacao_folha,
                            mao_obra,
                            escala,
                            horario_inicio,
                            horario_fim,
                            inicio_ferias,
                            fim_ferias,
                            nome_mae,
                            nome_pai,
                            cidade_nascimento,
                            endereco,
                            cep,
                            estado_civil,
                            salario,
                            contrato,
                            vencimento_cnh,
                            escolaridade
                        )
                        VALUES (
                            :nome,
                            :matricula,
                            :cpf,
                            :rg,
                            :cnh,
                            :ctps,
                            :pis,
                            :data_nascimento,
                            :funcao,
                            :data_admissao,
                            :data_funcao,
                            :situacao_folha,
                            :mao_obra,
                            :escala,
                            :horario_inicio,
                            :horario_fim,
                            :inicio_ferias,
                            :fim_ferias,
                            :nome_mae,
                            :nome_pai,
                            :cidade_nascimento,
                            :endereco,
                            :cep,
                            :estado_civil,
                            :salario,
                            :contrato,
                            :vencimento_cnh,
                            :escolaridade
                        )
                        """
                    )

                    conn.execute(
                        sql_insert,
                        {
                            "nome": nome,
                            "matricula": matricula,
                            "cpf": cpf,
                            "rg": rg,
                            "cnh": cnh,
                            "ctps": ctps,
                            "pis": pis,
                            "data_nascimento": data_nascimento,
                            "funcao": funcao,
                            "data_admissao": data_admissao,
                            "data_funcao": data_funcao,
                            "situacao_folha": situacao_folha,
                            "mao_obra": mao_obra,
                            "escala": escala,
                            "horario_inicio": horario_inicio,
                            "horario_fim": horario_fim,
                            "inicio_ferias": inicio_ferias,
                            "fim_ferias": fim_ferias,
                            "nome_mae": nome_mae,
                            "nome_pai": nome_pai,
                            "cidade_nascimento": cidade_nascimento,
                            "endereco": endereco,
                            "cep": cep,
                            "estado_civil": estado_civil,
                            "salario": salario,
                            "contrato": contrato,
                            "vencimento_cnh": vencimento_cnh,
                            "escolaridade": escolaridade,
                        },
                    )
                    conn.commit()
                    msg = "Colaborador cadastrado com sucesso."
                except SQLAlchemyError as e:
                    conn.rollback()
                    msg = f"Erro ao gravar colaborador: {e}"

        # --------------------- LISTAGEM (GET + após POST) ------------
        try:
            sql_lista = text(
                """
                SELECT
                    id,
                    nome,
                    matricula,
                    funcao,
                    situacao_folha,
                    mao_obra,
                    escala,
                    horario_inicio,
                    horario_fim
                FROM colaborador
                ORDER BY nome
                """
            )
            colaboradores = conn.execute(sql_lista).mappings().all()
        except SQLAlchemyError:
            colaboradores = []
            if msg is None:
                msg = "Erro ao consultar colaboradores."

    subnav = build_colab_subnav("registro")
    return render_template(
        "colaboradores/registro.html",
        subnav_links=subnav,
        msg=msg,
        colaboradores=colaboradores,
    )
