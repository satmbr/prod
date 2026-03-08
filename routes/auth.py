from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from werkzeug.security import check_password_hash, generate_password_hash
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


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("auth.login"))

        username = (session.get("username") or "").strip().lower()
        if username != "admin":
            abort(403)

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

        if usuario["deve_trocar_senha"]:
            flash("Troque sua senha antes de continuar.", "aviso")
            return redirect(url_for("auth.trocar_senha"))

        return redirect(url_for("index"))

    return render_template("auth/login.html")


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.get("/usuarios")
@login_required
@admin_required
def usuarios():
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    id,
                    nome,
                    username,
                    email,
                    ativo,
                    deve_trocar_senha,
                    ultimo_login,
                    criado_em
                FROM usuarios
                ORDER BY nome ASC
            """)
        ).mappings().all()

    return render_template("auth/usuarios.html", usuarios=rows)


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@login_required
@admin_required
def novo_usuario():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        senha = request.form.get("senha") or ""
        ativo = True if request.form.get("ativo") == "on" else False
        deve_trocar_senha = True if request.form.get("deve_trocar_senha") == "on" else False

        if not nome or not username or not senha:
            flash("Preencha nome, usuário e senha.", "erro")
            return render_template("auth/usuario_form.html", usuario=None)

        senha_hash = generate_password_hash(senha)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO usuarios (
                            nome, username, email, senha_hash, ativo,
                            deve_trocar_senha, criado_por
                        )
                        VALUES (
                            :nome, :username, :email, :senha_hash, :ativo,
                            :deve_trocar_senha, :criado_por
                        )
                    """),
                    {
                        "nome": nome,
                        "username": username,
                        "email": email if email else None,
                        "senha_hash": senha_hash,
                        "ativo": ativo,
                        "deve_trocar_senha": deve_trocar_senha,
                        "criado_por": session.get("usuario_id")
                    }
                )
            flash("Usuário criado com sucesso.", "sucesso")
            return redirect(url_for("auth.usuarios"))
        except Exception:
            flash("Não foi possível criar o usuário. Verifique se o username já existe.", "erro")
            return render_template("auth/usuario_form.html", usuario=None)

    return render_template("auth/usuario_form.html", usuario=None)


@bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def editar_usuario(usuario_id):
    with get_engine().connect() as conn:
        usuario = conn.execute(
            text("""
                SELECT id, nome, username, email, ativo, deve_trocar_senha
                FROM usuarios
                WHERE id = :id
            """),
            {"id": usuario_id}
        ).mappings().first()

    if not usuario:
        abort(404)

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        ativo = True if request.form.get("ativo") == "on" else False
        deve_trocar_senha = True if request.form.get("deve_trocar_senha") == "on" else False

        if not nome or not username:
            flash("Preencha nome e usuário.", "erro")
            return render_template("auth/usuario_form.html", usuario=usuario)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        UPDATE usuarios
                        SET
                            nome = :nome,
                            username = :username,
                            email = :email,
                            ativo = :ativo,
                            deve_trocar_senha = :deve_trocar_senha,
                            atualizado_em = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {
                        "id": usuario_id,
                        "nome": nome,
                        "username": username,
                        "email": email if email else None,
                        "ativo": ativo,
                        "deve_trocar_senha": deve_trocar_senha
                    }
                )
            flash("Usuário atualizado com sucesso.", "sucesso")
            return redirect(url_for("auth.usuarios"))
        except Exception:
            flash("Não foi possível atualizar. Verifique se o username já existe.", "erro")

            usuario = {
                "id": usuario_id,
                "nome": nome,
                "username": username,
                "email": email,
                "ativo": ativo,
                "deve_trocar_senha": deve_trocar_senha
            }
            return render_template("auth/usuario_form.html", usuario=usuario)

    return render_template("auth/usuario_form.html", usuario=usuario)


@bp.post("/usuarios/<int:usuario_id>/toggle")
@login_required
@admin_required
def toggle_usuario(usuario_id):
    with get_engine().begin() as conn:
        usuario = conn.execute(
            text("""
                SELECT id, username, ativo
                FROM usuarios
                WHERE id = :id
            """),
            {"id": usuario_id}
        ).mappings().first()

        if not usuario:
            abort(404)

        if usuario["username"].strip().lower() == "admin" and usuario["ativo"]:
            flash("O usuário administrador principal não pode ser inativado.", "erro")
            return redirect(url_for("auth.usuarios"))

        conn.execute(
            text("""
                UPDATE usuarios
                SET ativo = :ativo, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {
                "id": usuario_id,
                "ativo": not usuario["ativo"]
            }
        )

    flash("Status do usuário atualizado.", "sucesso")
    return redirect(url_for("auth.usuarios"))


@bp.route("/trocar-senha", methods=["GET", "POST"])
@login_required
def trocar_senha():
    if request.method == "POST":
        senha_atual = request.form.get("senha_atual") or ""
        nova_senha = request.form.get("nova_senha") or ""
        confirmar_senha = request.form.get("confirmar_senha") or ""

        if not nova_senha or not confirmar_senha:
            flash("Preencha os campos da nova senha.", "erro")
            return render_template("auth/trocar_senha.html")

        if nova_senha != confirmar_senha:
            flash("A confirmação da senha não confere.", "erro")
            return render_template("auth/trocar_senha.html")

        with get_engine().connect() as conn:
            usuario = conn.execute(
                text("""
                    SELECT id, senha_hash
                    FROM usuarios
                    WHERE id = :id
                """),
                {"id": session.get("usuario_id")}
            ).mappings().first()

        if not usuario:
            session.clear()
            return redirect(url_for("auth.login"))

        if not check_password_hash(usuario["senha_hash"], senha_atual):
            flash("Senha atual inválida.", "erro")
            return render_template("auth/trocar_senha.html")

        nova_hash = generate_password_hash(nova_senha)

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE usuarios
                    SET
                        senha_hash = :senha_hash,
                        deve_trocar_senha = FALSE,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": usuario["id"],
                    "senha_hash": nova_hash
                }
            )

        flash("Senha alterada com sucesso.", "sucesso")
        return redirect(url_for("index"))

    return render_template("auth/trocar_senha.html")


@bp.route("/usuarios/<int:usuario_id>/resetar-senha", methods=["GET", "POST"])
@login_required
@admin_required
def resetar_senha(usuario_id):
    with get_engine().connect() as conn:
        usuario = conn.execute(
            text("""
                SELECT id, nome, username
                FROM usuarios
                WHERE id = :id
            """),
            {"id": usuario_id}
        ).mappings().first()

    if not usuario:
        abort(404)

    if request.method == "POST":
        nova_senha = request.form.get("nova_senha") or ""
        confirmar_senha = request.form.get("confirmar_senha") or ""

        if not nova_senha or not confirmar_senha:
            flash("Preencha a nova senha e a confirmação.", "erro")
            return render_template("auth/trocar_senha.html", reset_user=usuario)

        if nova_senha != confirmar_senha:
            flash("A confirmação da senha não confere.", "erro")
            return render_template("auth/trocar_senha.html", reset_user=usuario)

        nova_hash = generate_password_hash(nova_senha)

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE usuarios
                    SET
                        senha_hash = :senha_hash,
                        deve_trocar_senha = TRUE,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": usuario_id,
                    "senha_hash": nova_hash
                }
            )

        flash("Senha redefinida com sucesso. O usuário deverá trocá-la no próximo acesso.", "sucesso")
        return redirect(url_for("auth.usuarios"))

    return render_template("auth/trocar_senha.html", reset_user=usuario)


@bp.app_errorhandler(403)
def acesso_negado(e):
    return render_template("auth/acesso_negado.html"), 403