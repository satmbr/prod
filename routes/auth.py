from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash
from db import get_engine
from sqlalchemy import text
from functools import wraps

bp = Blueprint("auth", __name__, url_prefix="/auth")


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped_view


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        senha = request.form.get("senha") or ""

        with get_engine().connect() as conn:
            usuario = conn.execute(
                text("""
                    SELECT id, nome, username, senha_hash, ativo, deve_trocar_senha
                    FROM usuarios
                    WHERE username = :username
                    LIMIT 1
                """),
                {"username": username}
            ).mappings().first()

        if not usuario:
            flash("Usuário ou senha inválidos.", "erro")
            return render_template("auth/login.html")

        if not usuario["ativo"]:
            flash("Usuário inativo. Procure o administrador.", "erro")
            return render_template("auth/login.html")

        if not check_password_hash(usuario["senha_hash"], senha):
            flash("Usuário ou senha inválidos.", "erro")
            return render_template("auth/login.html")

        session.clear()
        session["usuario_id"] = usuario["id"]
        session["usuario_nome"] = usuario["nome"]
        session["username"] = usuario["username"]

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE usuarios
                    SET ultimo_login = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {"id": usuario["id"]}
            )

        return redirect(url_for("index"))

    return render_template("auth/login.html")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))