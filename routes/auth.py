from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, send_file, Response
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_engine
from sqlalchemy import text
from functools import wraps
from datetime import datetime, timedelta
import io
import csv
from openpyxl import Workbook

bp = Blueprint("auth", __name__, url_prefix="/auth")

def registrar_log(evento, detalhes=None, usuario_id=None, username=None):
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO usuario_logs (
                        usuario_id,
                        username,
                        evento,
                        detalhes,
                        ip,
                        user_agent
                    )
                    VALUES (
                        :usuario_id,
                        :username,
                        :evento,
                        :detalhes,
                        :ip,
                        :user_agent
                    )
                """),
                {
                    "usuario_id": usuario_id,
                    "username": username,
                    "evento": evento,
                    "detalhes": detalhes,
                    "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
                    "user_agent": request.headers.get("User-Agent")
                }
            )
    except Exception:
        pass

def carregar_permissoes_usuario(usuario_id):
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT pm.modulo, pm.acao
                FROM usuarios u
                INNER JOIN perfil_permissoes pp ON pp.perfil_id = u.perfil_id
                INNER JOIN permissoes pm ON pm.id = pp.permissao_id
                WHERE u.id = :usuario_id
            """),
            {"usuario_id": usuario_id}
        ).mappings().all()

    return [f"{r['modulo']}:{r['acao']}" for r in rows]

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped_view


def perfil_required(*nomes_permitidos):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect(url_for("auth.login"))

            perfil_nome = (session.get("perfil_nome") or "").strip()
            if perfil_nome not in nomes_permitidos:
                abort(403)

            return view(*args, **kwargs)
        return wrapped_view
    return decorator


def permission_required(modulo, acao):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect(url_for("auth.login"))

            permissoes = session.get("permissoes", [])
            chave = f"{modulo}:{acao}"

            if chave not in permissoes and "auth:administrar" not in permissoes:
                abort(403)

            return view(*args, **kwargs)
        return wrapped_view
    return decorator


def admin_required(view):
    return permission_required("auth", "administrar")(view)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        senha = request.form.get("senha") or ""

        with get_engine().connect() as conn:
            usuario = conn.execute(
                text("""
                    SELECT
                        u.id,
                        u.nome,
                        u.username,
                        u.senha_hash,
                        u.ativo,
                        u.deve_trocar_senha,
                        u.perfil_id,
                        u.tentativas_login,
                        u.bloqueado_ate,
                        p.nome AS perfil_nome
                    FROM usuarios u
                    LEFT JOIN perfis p ON p.id = u.perfil_id
                    WHERE u.username = :username
                    LIMIT 1
                """),
                {"username": username}
            ).mappings().first()

        if not usuario:
            registrar_log(
                evento="login_invalido",
                detalhes="Usuário não encontrado",
                username=username
            )
            flash("Usuário ou senha inválidos.", "erro")
            return render_template("auth/login.html")

        if usuario["bloqueado_ate"] and usuario["bloqueado_ate"] > datetime.utcnow():
            registrar_log(
                evento="login_bloqueado_temporario",
                detalhes=f"Usuário bloqueado até {usuario['bloqueado_ate']}",
                usuario_id=usuario["id"],
                username=usuario["username"]
            )
            flash("Usuário temporariamente bloqueado por excesso de tentativas. Tente novamente mais tarde.", "erro")
            return render_template("auth/login.html")

        if not usuario["ativo"]:
            registrar_log(
                evento="login_bloqueado",
                detalhes="Usuário inativo",
                usuario_id=usuario["id"],
                username=usuario["username"]
            )
            flash("Usuário inativo. Procure o administrador.", "erro")
            return render_template("auth/login.html")

        if not check_password_hash(usuario["senha_hash"], senha):
            tentativas = (usuario["tentativas_login"] or 0) + 1
            bloqueado_ate = None

            if tentativas >= 5:
                bloqueado_ate = datetime.utcnow() + timedelta(minutes=15)

            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        UPDATE usuarios
                        SET
                            tentativas_login = :tentativas,
                            bloqueado_ate = :bloqueado_ate
                        WHERE id = :id
                    """),
                    {
                        "id": usuario["id"],
                        "tentativas": tentativas,
                        "bloqueado_ate": bloqueado_ate
                    }
                )

            if bloqueado_ate:
                registrar_log(
                    evento="usuario_bloqueado_temporariamente",
                    detalhes=f"Bloqueado após {tentativas} tentativas inválidas. Até {bloqueado_ate}",
                    usuario_id=usuario["id"],
                    username=usuario["username"]
                )
                flash("Usuário temporariamente bloqueado por excesso de tentativas. Tente novamente em 15 minutos.", "erro")
            else:
                registrar_log(
                    evento="login_invalido",
                    detalhes=f"Senha inválida. Tentativa {tentativas} de 5",
                    usuario_id=usuario["id"],
                    username=usuario["username"]
                )
                flash(f"Usuário ou senha inválidos. Tentativa {tentativas} de 5.", "erro")

            return render_template("auth/login.html")

        session.clear()
        session["usuario_id"] = usuario["id"]
        session["usuario_nome"] = usuario["nome"]
        session["username"] = usuario["username"]
        session["perfil_id"] = usuario["perfil_id"]
        session["perfil_nome"] = usuario["perfil_nome"]
        session["permissoes"] = carregar_permissoes_usuario(usuario["id"])
        
        session["ultimo_acesso"] = datetime.utcnow().timestamp()
        session.permanent = True        

        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE usuarios
                    SET
                        ultimo_login = CURRENT_TIMESTAMP,
                        tentativas_login = 0,
                        bloqueado_ate = NULL
                    WHERE id = :id
                """),
                {"id": usuario["id"]}
            )

        registrar_log(
            evento="login_sucesso",
            detalhes=f"Perfil: {usuario.get('perfil_nome') or 'Sem perfil'}",
            usuario_id=usuario["id"],
            username=usuario["username"]
        )

        if usuario["deve_trocar_senha"]:
            flash("Troque sua senha antes de continuar.", "aviso")
            return redirect(url_for("auth.trocar_senha"))

        return redirect(url_for("dashboard"))

    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    registrar_log(
        evento="logout",
        detalhes="Logout realizado com sucesso",
        usuario_id=session.get("usuario_id"),
        username=session.get("username")
    )
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
                    u.id,
                    u.nome,
                    u.username,
                    u.email,
                    u.ativo,
                    u.deve_trocar_senha,
                    u.ultimo_login,
                    u.criado_em,
                    u.perfil_id,
                    p.nome AS perfil_nome
                FROM usuarios u
                LEFT JOIN perfis p ON p.id = u.perfil_id
                ORDER BY u.nome ASC
            """)
        ).mappings().all()

    return render_template("auth/usuarios.html", usuarios=rows)


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@login_required
@admin_required
def novo_usuario():
    with get_engine().connect() as conn:
        perfis = conn.execute(
            text("""
                SELECT id, nome, descricao
                FROM perfis
                WHERE ativo = TRUE
                ORDER BY nome ASC
            """)
        ).mappings().all()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        senha = request.form.get("senha") or ""
        perfil_id = request.form.get("perfil_id")
        ativo = True if request.form.get("ativo") == "on" else False
        deve_trocar_senha = True if request.form.get("deve_trocar_senha") == "on" else False

        if not nome or not username or not senha or not perfil_id:
            flash("Preencha nome, usuário, senha e perfil.", "erro")
            return render_template("auth/usuario_form.html", usuario=None, perfis=perfis)

        senha_hash = generate_password_hash(senha)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO usuarios (
                            nome, username, email, senha_hash, perfil_id, ativo,
                            deve_trocar_senha, criado_por
                        )
                        VALUES (
                            :nome, :username, :email, :senha_hash, :perfil_id, :ativo,
                            :deve_trocar_senha, :criado_por
                        )
                    """),
                    {
                        "nome": nome,
                        "username": username,
                        "email": email if email else None,
                        "senha_hash": senha_hash,
                        "perfil_id": int(perfil_id),
                        "ativo": ativo,
                        "deve_trocar_senha": deve_trocar_senha,
                        "criado_por": session.get("usuario_id")
                    }
                )
            registrar_log(
                evento="usuario_criado",
                detalhes=f"Novo usuário criado: {username}",
                usuario_id=session.get("usuario_id"),
                username=session.get("username")
            )                
            flash("Usuário criado com sucesso.", "sucesso")
            return redirect(url_for("auth.usuarios"))
        except Exception:
            flash("Não foi possível criar o usuário. Verifique se o username já existe.", "erro")
            return render_template("auth/usuario_form.html", usuario=None, perfis=perfis)

    return render_template("auth/usuario_form.html", usuario=None, perfis=perfis)


@bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def editar_usuario(usuario_id):
    with get_engine().connect() as conn:
        usuario = conn.execute(
            text("""
                SELECT id, nome, username, email, ativo, deve_trocar_senha, perfil_id
                FROM usuarios
                WHERE id = :id
            """),
            {"id": usuario_id}
        ).mappings().first()

        perfis = conn.execute(
            text("""
                SELECT id, nome, descricao
                FROM perfis
                WHERE ativo = TRUE
                ORDER BY nome ASC
            """)
        ).mappings().all()

    if not usuario:
        abort(404)

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        perfil_id = request.form.get("perfil_id")
        ativo = True if request.form.get("ativo") == "on" else False
        deve_trocar_senha = True if request.form.get("deve_trocar_senha") == "on" else False

        if not nome or not username or not perfil_id:
            flash("Preencha nome, usuário e perfil.", "erro")
            return render_template("auth/usuario_form.html", usuario=usuario, perfis=perfis)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        UPDATE usuarios
                        SET
                            nome = :nome,
                            username = :username,
                            email = :email,
                            perfil_id = :perfil_id,
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
                        "perfil_id": int(perfil_id),
                        "ativo": ativo,
                        "deve_trocar_senha": deve_trocar_senha
                    }
                )
            registrar_log(
                evento="usuario_editado",
                detalhes=f"Usuário editado: {username} (ID {usuario_id})",
                usuario_id=session.get("usuario_id"),
                username=session.get("username")
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
                "perfil_id": int(perfil_id),
                "ativo": ativo,
                "deve_trocar_senha": deve_trocar_senha
            }
            return render_template("auth/usuario_form.html", usuario=usuario, perfis=perfis)

    return render_template("auth/usuario_form.html", usuario=usuario, perfis=perfis)


@bp.post("/usuarios/<int:usuario_id>/toggle")
@login_required
@admin_required
def toggle_usuario(usuario_id):
    with get_engine().begin() as conn:
        usuario = conn.execute(
            text("""
                SELECT u.id, u.username, u.ativo, p.nome AS perfil_nome
                FROM usuarios u
                LEFT JOIN perfis p ON p.id = u.perfil_id
                WHERE u.id = :id
            """),
            {"id": usuario_id}
        ).mappings().first()

        if not usuario:
            abort(404)

        if usuario["perfil_nome"] == "Administrador" and usuario["ativo"]:
            qtd_admins_ativos = conn.execute(
                text("""
                    SELECT COUNT(*) AS total
                    FROM usuarios u
                    INNER JOIN perfis p ON p.id = u.perfil_id
                    WHERE p.nome = 'Administrador'
                      AND u.ativo = TRUE
                """)
            ).scalar()

            if qtd_admins_ativos <= 1:
                flash("Não é permitido inativar o último administrador ativo.", "erro")
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
    registrar_log(
        evento="usuario_status_alterado",
        detalhes=f"Usuário ID {usuario_id} teve status alterado para {'ativo' if not usuario['ativo'] else 'inativo'}",
        usuario_id=session.get("usuario_id"),
        username=session.get("username")
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
        registrar_log(
            evento="senha_alterada",
            detalhes="Usuário alterou a própria senha",
            usuario_id=session.get("usuario_id"),
            username=session.get("username")
        )
        flash("Senha alterada com sucesso.", "sucesso")
        return redirect(url_for("dashboard"))

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
        registrar_log(
            evento="senha_resetada",
            detalhes=f"Senha resetada para o usuário ID {usuario_id}",
            usuario_id=session.get("usuario_id"),
            username=session.get("username")
        )
        flash("Senha redefinida com sucesso. O usuário deverá trocá-la no próximo acesso.", "sucesso")
        return redirect(url_for("auth.usuarios"))

    return render_template("auth/trocar_senha.html", reset_user=usuario)


@bp.get("/perfis")
@login_required
@admin_required
def perfis():
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, nome, descricao, ativo, criado_em
                FROM perfis
                ORDER BY nome ASC
            """)
        ).mappings().all()

    return render_template("auth/perfis.html", perfis=rows)


@bp.route("/perfis/novo", methods=["GET", "POST"])
@login_required
@admin_required
def novo_perfil():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        ativo = True if request.form.get("ativo") == "on" else False

        if not nome:
            flash("Informe o nome do perfil.", "erro")
            return render_template("auth/perfil_form.html", perfil=None)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO perfis (nome, descricao, ativo)
                        VALUES (:nome, :descricao, :ativo)
                    """),
                    {
                        "nome": nome,
                        "descricao": descricao if descricao else None,
                        "ativo": ativo
                    }
                )
            registrar_log(
                evento="perfil_criado",
                detalhes=f"Perfil criado: {nome}",
                usuario_id=session.get("usuario_id"),
                username=session.get("username")
            )                
            flash("Perfil criado com sucesso.", "sucesso")
            return redirect(url_for("auth.perfis"))
        except Exception:
            flash("Não foi possível criar o perfil. Verifique se o nome já existe.", "erro")
            return render_template("auth/perfil_form.html", perfil=None)

    return render_template("auth/perfil_form.html", perfil=None)


@bp.route("/perfis/<int:perfil_id>/editar", methods=["GET", "POST"])
@login_required
@admin_required
def editar_perfil(perfil_id):
    with get_engine().connect() as conn:
        perfil = conn.execute(
            text("""
                SELECT id, nome, descricao, ativo
                FROM perfis
                WHERE id = :id
            """),
            {"id": perfil_id}
        ).mappings().first()

    if not perfil:
        abort(404)

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        ativo = True if request.form.get("ativo") == "on" else False

        if not nome:
            flash("Informe o nome do perfil.", "erro")
            return render_template("auth/perfil_form.html", perfil=perfil)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        UPDATE perfis
                        SET
                            nome = :nome,
                            descricao = :descricao,
                            ativo = :ativo
                        WHERE id = :id
                    """),
                    {
                        "id": perfil_id,
                        "nome": nome,
                        "descricao": descricao if descricao else None,
                        "ativo": ativo
                    }
                )
            registrar_log(
                evento="perfil_editado",
                detalhes=f"Perfil editado: {nome} (ID {perfil_id})",
                usuario_id=session.get("usuario_id"),
                username=session.get("username")
            )                
            flash("Perfil atualizado com sucesso.", "sucesso")
            return redirect(url_for("auth.perfis"))
        except Exception:
            flash("Não foi possível atualizar o perfil. Verifique se o nome já existe.", "erro")

            perfil = {
                "id": perfil_id,
                "nome": nome,
                "descricao": descricao,
                "ativo": ativo
            }
            return render_template("auth/perfil_form.html", perfil=perfil)

    return render_template("auth/perfil_form.html", perfil=perfil)

@bp.get("/perfis/<int:perfil_id>/permissoes")
@login_required
@admin_required
def permissoes_perfil(perfil_id):
    with get_engine().connect() as conn:
        perfil = conn.execute(
            text("""
                SELECT id, nome, descricao, ativo
                FROM perfis
                WHERE id = :id
            """),
            {"id": perfil_id}
        ).mappings().first()

        if not perfil:
            abort(404)

        permissoes = conn.execute(
            text("""
                SELECT
                    pm.id,
                    pm.modulo,
                    pm.acao,
                    pm.descricao,
                    CASE
                        WHEN pp.id IS NOT NULL THEN TRUE
                        ELSE FALSE
                    END AS marcado
                FROM permissoes pm
                LEFT JOIN perfil_permissoes pp
                    ON pp.permissao_id = pm.id
                   AND pp.perfil_id = :perfil_id
                ORDER BY pm.modulo ASC, pm.acao ASC
            """),
            {"perfil_id": perfil_id}
        ).mappings().all()

    return render_template("auth/perfil_permissoes.html", perfil=perfil, permissoes=permissoes)

@bp.post("/perfis/<int:perfil_id>/permissoes")
@login_required
@admin_required
def salvar_permissoes_perfil(perfil_id):
    permissoes_ids = request.form.getlist("permissoes")

    with get_engine().begin() as conn:
        perfil = conn.execute(
            text("SELECT id, nome FROM perfis WHERE id = :id"),
            {"id": perfil_id}
        ).mappings().first()

        if not perfil:
            abort(404)

        conn.execute(
            text("DELETE FROM perfil_permissoes WHERE perfil_id = :perfil_id"),
            {"perfil_id": perfil_id}
        )

        for permissao_id in permissoes_ids:
            conn.execute(
                text("""
                    INSERT INTO perfil_permissoes (perfil_id, permissao_id)
                    VALUES (:perfil_id, :permissao_id)
                    ON CONFLICT (perfil_id, permissao_id) DO NOTHING
                """),
                {
                    "perfil_id": perfil_id,
                    "permissao_id": int(permissao_id)
                }
            )
    registrar_log(
        evento="permissoes_perfil_alteradas",
        detalhes=f"Permissões alteradas para o perfil ID {perfil_id}",
        usuario_id=session.get("usuario_id"),
        username=session.get("username")
    )
    flash("Permissões do perfil atualizadas com sucesso.", "sucesso")
    return redirect(url_for("auth.permissoes_perfil", perfil_id=perfil_id))

@bp.app_errorhandler(403)
def acesso_negado(e):
    return render_template("auth/acesso_negado.html"), 403

def montar_filtros_logs():
    username  = (request.args.get("username")  or "").strip()
    evento    = (request.args.get("evento")    or "").strip()
    data_ini  = (request.args.get("data_ini")  or "").strip()
    data_fim  = (request.args.get("data_fim")  or "").strip()
    ip_filtro = (request.args.get("ip")        or "").strip()

    where = []
    params = {}

    if username:
        where.append("username ILIKE :username")
        params["username"] = f"%{username}%"

    if evento:
        where.append("evento ILIKE :evento")
        params["evento"] = f"%{evento}%"

    if data_ini:
        where.append("criado_em >= :data_ini")
        params["data_ini"] = f"{data_ini} 00:00:00"

    if data_fim:
        where.append("criado_em <= :data_fim")
        params["data_fim"] = f"{data_fim} 23:59:59"

    if ip_filtro:
        where.append("ip ILIKE :ip")
        params["ip"] = f"%{ip_filtro}%"

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    filtros = {
        "username": username,
        "evento": evento,
        "data_ini": data_ini,
        "data_fim": data_fim,
        "ip": ip_filtro,
    }

    return where_sql, params, filtros


@bp.get("/logs")
@login_required
@admin_required
def logs():
    POR_PAGINA = 100
    pagina = max(1, int(request.args.get("pagina", 1) or 1))

    where_sql, params, filtros = montar_filtros_logs()

    engine = get_engine()
    with engine.connect() as conn:

        # Total de registros (para paginação)
        total_rows = conn.execute(
            text(f"SELECT COUNT(*) FROM usuario_logs {where_sql}"), params
        ).scalar() or 0

        total_paginas = max(1, (total_rows + POR_PAGINA - 1) // POR_PAGINA)
        pagina = min(pagina, total_paginas)
        offset = (pagina - 1) * POR_PAGINA

        params_pag = dict(params)
        params_pag["limit"] = POR_PAGINA
        params_pag["offset"] = offset

        rows = conn.execute(text(f"""
            SELECT id, usuario_id, username, evento, detalhes, ip, user_agent, criado_em
            FROM usuario_logs
            {where_sql}
            ORDER BY criado_em DESC
            LIMIT :limit OFFSET :offset
        """), params_pag).mappings().all()

        # Estatísticas gerais (últimas 24h e totais)
        stats = conn.execute(text("""
            SELECT
                COUNT(*) AS total_geral,
                COUNT(*) FILTER (WHERE criado_em >= NOW() - INTERVAL '24 hours') AS ultimas_24h,
                COUNT(*) FILTER (WHERE criado_em >= NOW() - INTERVAL '7 days')  AS ultimos_7d,
                COUNT(DISTINCT username) AS usuarios_distintos,
                COUNT(*) FILTER (WHERE evento ILIKE '%login%')  AS total_logins,
                COUNT(*) FILTER (WHERE evento ILIKE '%erro%' OR evento ILIKE '%falha%' OR evento ILIKE '%negado%') AS total_erros
            FROM usuario_logs
        """)).mappings().first()

        # Top 5 usuários mais ativos
        top_usuarios = conn.execute(text("""
            SELECT username, COUNT(*) AS qtd
            FROM usuario_logs
            WHERE username IS NOT NULL AND username <> ''
            GROUP BY username
            ORDER BY qtd DESC
            LIMIT 5
        """)).mappings().all()

        # Top 5 eventos mais frequentes
        top_eventos = conn.execute(text("""
            SELECT evento, COUNT(*) AS qtd
            FROM usuario_logs
            WHERE evento IS NOT NULL
            GROUP BY evento
            ORDER BY qtd DESC
            LIMIT 5
        """)).mappings().all()

        # Eventos por dia (últimos 14 dias) para mini-gráfico
        atividade_diaria = conn.execute(text("""
            SELECT
                TO_CHAR(criado_em::date, 'DD/MM') AS dia,
                COUNT(*) AS qtd
            FROM usuario_logs
            WHERE criado_em >= NOW() - INTERVAL '14 days'
            GROUP BY criado_em::date
            ORDER BY criado_em::date ASC
        """)).mappings().all()

    return render_template(
        "auth/logs.html",
        logs=rows,
        filtros=filtros,
        pagina=pagina,
        total_paginas=total_paginas,
        total_rows=total_rows,
        stats=stats,
        top_usuarios=top_usuarios,
        top_eventos=top_eventos,
        atividade_diaria=atividade_diaria,
    )

@bp.get("/minha-conta")
@login_required
def minha_conta():
    with get_engine().connect() as conn:
        usuario = conn.execute(
            text("""
                SELECT
                    u.id,
                    u.nome,
                    u.username,
                    u.email,
                    u.ativo,
                    u.ultimo_login,
                    u.criado_em,
                    p.nome AS perfil_nome
                FROM usuarios u
                LEFT JOIN perfis p ON p.id = u.perfil_id
                WHERE u.id = :id
            """),
            {"id": session.get("usuario_id")}
        ).mappings().first()

    if not usuario:
        session.clear()
        return redirect(url_for("auth.login"))

    return render_template("auth/minha_conta.html", usuario=usuario)

@bp.get("/logs/exportar-csv")
@login_required
@admin_required
def exportar_logs_csv():
    where_sql, params, _ = montar_filtros_logs()

    sql = f"""
        SELECT
            criado_em,
            username,
            evento,
            detalhes,
            ip,
            user_agent
        FROM usuario_logs
        {where_sql}
        ORDER BY criado_em DESC
        LIMIT 5000
    """

    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(["Data/Hora", "Usuário", "Evento", "Detalhes", "IP", "User-Agent"])

    for row in rows:
        writer.writerow([
            row["criado_em"],
            row["username"] or "",
            row["evento"] or "",
            row["detalhes"] or "",
            row["ip"] or "",
            row["user_agent"] or ""
        ])

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=auditoria_logs.csv"
        }
    )

@bp.get("/logs/exportar-excel")
@login_required
@admin_required
def exportar_logs_excel():
    where_sql, params, _ = montar_filtros_logs()

    sql = f"""
        SELECT
            criado_em,
            username,
            evento,
            detalhes,
            ip,
            user_agent
        FROM usuario_logs
        {where_sql}
        ORDER BY criado_em DESC
        LIMIT 5000
    """

    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Auditoria"

    headers = ["Data/Hora", "Usuário", "Evento", "Detalhes", "IP", "User-Agent"]
    ws.append(headers)

    for row in rows:
        ws.append([
            str(row["criado_em"] or ""),
            row["username"] or "",
            row["evento"] or "",
            row["detalhes"] or "",
            row["ip"] or "",
            row["user_agent"] or ""
        ])

    for col in ws.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                value_len = len(str(cell.value)) if cell.value else 0
                if value_len > max_length:
                    max_length = value_len
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 50)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="auditoria_logs.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
