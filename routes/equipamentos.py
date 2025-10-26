from flask import Blueprint, render_template, url_for, request, redirect
from sqlalchemy import text
from db import get_engine
from datetime import date

bp = Blueprint("equipamentos", __name__)

# ----------------------------
# Helpers
# ----------------------------
def _subnav(active: str):
    return [
        {"text": "Cadastro",   "href": url_for("equipamentos.cadastro"),   "active": active == "cadastro"},
        {"text": "PartDiaria", "href": url_for("equipamentos.partdiaria"), "active": active == "partdiaria"},
    ]

# ----------------------------
# GETs
# ----------------------------
@bp.get("/")
def index():
    return render_template("equipamentos/index.html", subnav_links=_subnav(""))

@bp.get("/cadastro")
def cadastro():
    # Se quiser, depois conectamos no banco para listar equipamentos
    return render_template("equipamentos/cadastro.html", subnav_links=_subnav("cadastro"), msg=request.args.get("msg"))

@bp.get("/partdiaria")
def partdiaria():
    # Filtros simples (placeholder)
    filtros = {
        "ini": request.args.get("ini"),
        "fim": request.args.get("fim"),
        "equip": request.args.get("equip"),
    }
    resultados = []  # depois buscamos no banco
    return render_template("equipamentos/partdiaria.html",
                           subnav_links=_subnav("partdiaria"),
                           filtros=filtros, resultados=resultados,
                           today=date.today().isoformat(),
                           msg=request.args.get("msg"))

# ----------------------------
# POSTs (placeholders prontos para ligar no banco depois)
# ----------------------------
@bp.post("/cadastro/create")
def equip_create():
    # nome = request.form.get("nome") ...
    return redirect(url_for("equipamentos.cadastro", msg="(demo) Equipamento cadastrado."))

@bp.post("/cadastro/update")
def equip_update():
    return redirect(url_for("equipamentos.cadastro", msg="(demo) Equipamento atualizado."))

@bp.post("/cadastro/delete")
def equip_delete():
    return redirect(url_for("equipamentos.cadastro", msg="(demo) Equipamento excluído."))

@bp.post("/partdiaria/create")
def part_create():
    return redirect(url_for("equipamentos.partdiaria", msg="(demo) Lançamento salvo."))

@bp.post("/partdiaria/item/update")
def part_item_update():
    return redirect(url_for("equipamentos.partdiaria", msg="(demo) Lançamento atualizado."))

@bp.post("/partdiaria/item/delete")
def part_item_delete():
    return redirect(url_for("equipamentos.partdiaria", msg="(demo) Lançamento excluído."))
