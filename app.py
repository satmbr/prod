from flask import Flask
import os

def create_app():
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "Hello from Railway (satmbr/prod)!"

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
