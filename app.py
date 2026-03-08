from flask import Flask, session, redirect, url_for, request, flash
import os
from datetime import timedelta, datetime

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)

    @app.before_request
    def controlar_sessao():
        rotas_livres = {
            "auth.login",
            "static"
        }

        if request.endpoint in rotas_livres or request.endpoint is None:
            return

        if "usuario_id" in session:
            agora = datetime.utcnow().timestamp()
            ultimo_acesso = session.get("ultimo_acesso")

            if ultimo_acesso:
                tempo_inativo = agora - ultimo_acesso
                if tempo_inativo > 1800:  # 30 minutos
                    session.clear()
                    flash("Sua sessão expirou por inatividade. Faça login novamente.", "erro")
                    return redirect(url_for("auth.login"))

            session["ultimo_acesso"] = agora
            session.permanent = True

    @app.context_processor
    def inject_user():
        return {
            "current_user_name": session.get("usuario_nome"),
            "usuario_logado": "usuario_id" in session,
            "current_user_profile": session.get("perfil_nome"),
            "current_user_permissions": session.get("permissoes", [])
        }

    from routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from routes.operacao import bp as operacao_bp
    app.register_blueprint(operacao_bp, url_prefix="/operacao")

    from routes.equipamentos import bp as equipamentos_bp
    app.register_blueprint(equipamentos_bp, url_prefix="/equipamentos")

    from routes.colaboradores import bp as colaboradores_bp
    app.register_blueprint(colaboradores_bp)

@app.get("/")
def home():
    from flask import render_template
    return render_template("home_publica.html")


@app.get("/dashboard")
def dashboard():
    from flask import render_template

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

    return render_template("index.html", cards=cards)

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)