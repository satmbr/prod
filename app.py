from flask import Flask, request
import os

def create_app():
    app = Flask(__name__)

    # injeta o nome do usuário em todos os templates
    @app.context_processor
    def inject_user():
        name = (request.args.get("user")
                or os.getenv("APP_USER")
                or "Usuário")
        return {"current_user_name": name}

    # registra o blueprint de Operação
    from routes.operacao import bp as operacao_bp
    app.register_blueprint(operacao_bp, url_prefix="/operacao")

    @app.get("/")
    def index():
        from flask import render_template
        return render_template("index.html")

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
