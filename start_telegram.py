import os

from routes.financeiro_novo.services.pagamentos_telegram import configurar_webhook


configurar_webhook()
porta = os.getenv("PORT", "8080")
os.execvp("gunicorn", [
    "gunicorn", "telegram_bot:app", "--bind", f"0.0.0.0:{porta}",
    "--workers", "2", "--threads", "4", "--timeout", "120",
])
