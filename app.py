from flask import Flask, render_template, request
import os

def create_app():
    app = Flask(__name__)

    # Origem do nome do usuário (temporário):
    # 1) query param ?user=Fulano
    # 2) variável de ambiente APP_USER
    # 3) fallback "Usuário"
    def resolve_user_name():
        return request.args.get("user") or os.getenv("APP_USER") or "Usuário"

    @app.get("/")
    def index():
        return render_template("index.html", current_user_name=resolve_user_name())

    # healthcheck
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
