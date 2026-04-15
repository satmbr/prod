from flask import render_template, request, redirect, url_for, flash, abort
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_dois_routes import bp, build_financeiro_dois_subnav, _nome_preenchido


@bp.route("/reembolsos-real")
@login_required
@permission_required("financeiro", "visualizar")
def reembolsos_real_teste():
    return render_template(
        "financeiro_dois/reembolsos.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolsos=[],
    )