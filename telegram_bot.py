import os

from flask import Flask, abort, request

from routes.financeiro_novo.services.pagamentos_telegram import (
    processar_update,
    webhook_autentico,
)


def create_telegram_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    @app.after_request
    def proteger(resposta):
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return resposta

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "telegram-bot"}

    @app.post("/telegram/webhook")
    def webhook():
        if not webhook_autentico(request.headers.get("X-Telegram-Bot-Api-Secret-Token")):
            abort(403)
        update = request.get_json(silent=True)
        if not isinstance(update, dict):
            abort(400)
        processar_update(update)
        return {"ok": True}

    return app


app = create_telegram_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
