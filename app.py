from flask import Flask, render_template, request, url_for
import os

def create_app():
    app = Flask(__name__)

    # Nome do usuário mostrado no topo (APP_USER no Railway, ou ?user=Fulano)
    def resolve_user_name():
        return request.args.get("user") or os.getenv("APP_USER") or "Usuário"

    # Subnav exclusivo da seção Operação
    def producao_subnav(active: str):
        return [
            {"text": "Produção", "href": url_for("operacao_producao"), "active": active == "producao"},
            {"text": "Registro",  "href": url_for("operacao_registro"),  "active": active == "registro"},
            {"text": "Cadastro",  "href": url_for("operacao_cadastro"),  "active": active == "cadastro"},
        ]

    @app.get("/")
    def index():
        return render_template("index.html", current_user_name=resolve_user_name())

    # ===== Seção: Operação =====
    @app.get("/operacao")
    def operacao_index():
        # Ao entrar na seção, APENAS mostra os sublinks (nenhum ativo ainda)
        return render_template(
            "operacao/index.html",
            current_user_name=resolve_user_name(),
            subnav_links=producao_subnav(active=""),
        )

    @app.get("/operacao/producao")
    def operacao_producao():
        return render_template(
            "operacao/produção.html",   # arquivo com acento
            current_user_name=resolve_user_name(),
            subnav_links=producao_subnav(active="producao"),
        )

    @app.get("/operacao/registro")
    def operacao_registro():
        return render_template(
            "operacao/registro.html",
            current_user_name=resolve_user_name(),
            subnav_links=producao_subnav(active="registro"),
        )

    @app.get("/operacao/cadastro")
    def operacao_cadastro():
        return render_template(
            "operacao/cadastro.html",
            current_user_name=resolve_user_name(),
            subnav_links=producao_subnav(active="cadastro"),
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}, 200

    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
