from flask import Flask, session, redirect, url_for, request, flash, render_template, abort
from flask_wtf.csrf import CSRFProtect, CSRFError
import os
from datetime import timedelta, datetime

csrf = CSRFProtect()

def create_app():
    app = Flask(__name__)
    secret_key = os.getenv("SECRET_KEY")
    if not secret_key:
        raise RuntimeError("SECRET_KEY não definida no ambiente.")

    em_railway = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))
    cookie_secure = os.getenv("SESSION_COOKIE_SECURE")

    app.config["SECRET_KEY"] = secret_key
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = (
        cookie_secure.lower() in {"1", "true", "yes", "on"}
        if cookie_secure is not None
        else em_railway
    )
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))
    upload_root = os.getenv("UPLOAD_ROOT")
    if not upload_root and os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
        upload_root = os.path.join(os.getenv("RAILWAY_VOLUME_MOUNT_PATH"), "uploads")
    app.config["UPLOAD_ROOT"] = os.path.abspath(upload_root or os.path.join(app.instance_path, "uploads"))

    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def csrf_error(_erro):
        return "Requisição inválida ou expirada. Atualize a página e tente novamente.", 400

    @app.before_request
    def controlar_sessao():
        if request.endpoint == "static":
            arquivo_estatico = (request.view_args or {}).get("filename", "")
            caminho = str(arquivo_estatico).replace("\\", "/").lstrip("/")
            if caminho.startswith("uploads/"):
                abort(404)

        rotas_livres = {
            "auth.login",
            "auth.logout",
            "home",
            "health",
            "static",
        }

        if request.endpoint in rotas_livres or request.endpoint is None:
            return

        # Redireciona usuário não autenticado para qualquer rota protegida
        if "usuario_id" not in session:
            flash("Faça login para acessar esta página.", "warning")
            return redirect(url_for("auth.login"))

        agora = datetime.utcnow().timestamp()
        ultimo_acesso = session.get("ultimo_acesso")

        if ultimo_acesso:
            tempo_inativo = agora - ultimo_acesso
            if tempo_inativo > 1800:  # 30 minutos
                session.clear()
                flash("Sua sessão expirou por inatividade. Faça login novamente.", "warning")
                return redirect(url_for("auth.login"))

        session["ultimo_acesso"] = agora
        session.permanent = True

    @app.context_processor
    def inject_user():
        return {
            "current_user_name": session.get("usuario_nome"),
            "usuario_logado": "usuario_id" in session,
            "current_user_profile": session.get("perfil_nome"),
            "current_user_permissions": session.get("permissoes", []),
            "subnav_links": []
        }

    from routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from routes.operacao import bp as operacao_bp
    app.register_blueprint(operacao_bp, url_prefix="/operacao")

    from routes.equipamentos import bp as equipamentos_bp
    app.register_blueprint(equipamentos_bp, url_prefix="/equipamentos")

    from routes.colaboradores import bp as colaboradores_bp
    app.register_blueprint(colaboradores_bp)
    
    from routes.financeiro_dois_routes import bp as financeiro_dois_bp
    app.register_blueprint(financeiro_dois_bp)

    from routes.financeiro_novo import bp as financeiro_novo_bp
    app.register_blueprint(financeiro_novo_bp)

    @app.get("/")
    def home():
        return render_template("home_publica.html")

    @app.get("/dashboard")
    def dashboard():
        if "usuario_id" not in session:
            return redirect(url_for("auth.login"))

        permissoes = session.get("permissoes", [])
        cards = []

        if "operacao:visualizar" in permissoes or "auth:administrar" in permissoes:
            cards.append({
                "titulo": "Operação",
                "descricao": "Acompanhe produção, cadastros e registros do módulo de operação.",
                "href": url_for("operacao.index"),
                "botao": "Acessar módulo"
            })

        if "equipamentos:visualizar" in permissoes or "auth:administrar" in permissoes:
            cards.append({
                "titulo": "Equipamentos",
                "descricao": "Consulte e gerencie cadastros, controles e informações dos equipamentos.",
                "href": url_for("equipamentos.index"),
                "botao": "Acessar módulo"
            })

        if "colaboradores:visualizar" in permissoes or "auth:administrar" in permissoes:
            cards.append({
                "titulo": "Colaboradores",
                "descricao": "Visualize e mantenha os registros e dados dos colaboradores.",
                "href": url_for("colaboradores.registro"),
                "botao": "Acessar módulo"
            })

        if "auth:administrar" in permissoes:
            cards.append({
                "titulo": "Administração",
                "descricao": "Gerencie usuários, perfis, permissões e auditoria do sistema.",
                "href": url_for("auth.usuarios"),
                "botao": "Abrir administração"
            })
            
        if "financeiro:visualizar" in permissoes or "auth:administrar" in permissoes:
            cards.append({
                "titulo": "Financeiro",
                "descricao": "Controle OM, RD, despesas, notas de débito, reembolsos e previsões financeiras.",
                "href": url_for("financeiro_dois.index"),
                "botao": "Acessar módulo"
            })

        if "financeiro_novo:visualizar" in permissoes or "auth:administrar" in permissoes:
            cards.append({
                "titulo": "Financeiro Novo · Homologação",
                "descricao": "Novo módulo financeiro independente, iniciando vazio e sem acesso aos dados anteriores.",
                "href": url_for("financeiro_novo.index"),
                "botao": "Abrir homologação"
            })

        return render_template("index.html", cards=cards)

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
