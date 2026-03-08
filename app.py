from flask import Flask, session, redirect, url_for, request
import os

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")

    @app.context_processor
    def inject_user():
        return {
            "current_user_name": session.get("usuario_nome"),
            "usuario_logado": "usuario_id" in session,
            "current_user_profile": session.get("perfil_nome")
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
    def index():
        from flask import render_template
        if "usuario_id" not in session:
            return redirect(url_for("auth.login"))
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)