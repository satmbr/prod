from flask import Flask, render_template
import os

def create_app():
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template("index.html")

    # healthcheck p/ uptime
    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
