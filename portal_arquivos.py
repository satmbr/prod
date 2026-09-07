import os

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import text
from werkzeug.exceptions import RequestEntityTooLarge

from db import get_engine
from routes.financeiro_novo.services.pagamentos_bucket import (
    PASTAS,
    PASTAS_GRAVAVEIS,
    PagamentosStorageErro,
    excluir_arquivo,
    listar_arquivos,
    reenviar_arquivo_erro,
    renomear_arquivo,
    enviar_arquivo,
    url_temporaria,
)


ROTULOS = {
    "novas_contas": "Novas contas",
    "contas_controladas": "Contas controladas",
    "contas_quitadas": "Contas quitadas",
    "comprovantes": "Comprovantes",
    "contas_com_erro": "Contas com erro",
}


def _perfil(token: str) -> dict:
    if len(token) < 32 or len(token) > 100:
        abort(404)
    with get_engine().connect() as conn:
        perfil = conn.execute(text("""
            SELECT id,nome,matricula,gmail,portal_token,storage_prefix
            FROM financeiro3_pagamento_perfis
            WHERE portal_token=:token AND ativo
        """), {"token": token}).mappings().first()
    if not perfil:
        abort(404)
    return dict(perfil)


def create_portal_app():
    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = os.getenv("PORTAL_SECRET_KEY") or os.getenv("SECRET_KEY")
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("PORTAL_SECRET_KEY ou SECRET_KEY não definida no ambiente.")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 20 * 1024 * 1024))

    @app.after_request
    def proteger_resposta(resposta):
        resposta.headers["Cache-Control"] = "no-store"
        resposta.headers["Referrer-Policy"] = "no-referrer"
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'"
        )
        resposta.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return resposta

    @app.errorhandler(RequestEntityTooLarge)
    def arquivo_grande(_erro):
        return "O envio ultrapassa o limite permitido.", 413

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "portal-arquivos"}

    @app.get("/p/<token>/")
    @app.get("/p/<token>/<pasta>")
    def arquivos(token, pasta="novas_contas"):
        perfil = _perfil(token)
        if pasta not in PASTAS:
            abort(404)
        try:
            arquivos_pasta = listar_arquivos(perfil, pasta)
            contagens = {item: len(listar_arquivos(perfil, item)) for item in PASTAS}
        except PagamentosStorageErro as exc:
            arquivos_pasta = []
            contagens = {item: 0 for item in PASTAS}
            flash(str(exc), "erro")
        return render_template(
            "portal_arquivos.html", perfil=perfil, token=token, pasta=pasta,
            pastas=PASTAS, rotulos=ROTULOS, arquivos=arquivos_pasta,
            contagens=contagens, gravavel=pasta in PASTAS_GRAVAVEIS,
            editavel=pasta in PASTAS_GRAVAVEIS or pasta == "contas_com_erro",
        )

    @app.post("/p/<token>/<pasta>/enviar")
    def enviar(token, pasta):
        perfil = _perfil(token)
        if pasta not in PASTAS_GRAVAVEIS:
            abort(403)
        arquivos = [item for item in request.files.getlist("arquivos") if item and item.filename]
        if not arquivos:
            flash("Selecione ao menos um arquivo.", "erro")
        else:
            enviados = 0
            erros = []
            for arquivo in arquivos:
                try:
                    enviar_arquivo(perfil, pasta, arquivo)
                    enviados += 1
                except Exception as exc:
                    erros.append(f"{arquivo.filename}: {exc}")
            if enviados:
                flash(f"{enviados} arquivo(s) enviado(s).", "sucesso")
            if erros:
                flash(" ".join(erros), "erro")
        return redirect(url_for("arquivos", token=token, pasta=pasta))

    @app.get("/p/<token>/arquivo/<arquivo_id>")
    def abrir(token, arquivo_id):
        perfil = _perfil(token)
        try:
            return redirect(url_temporaria(perfil, arquivo_id), code=302)
        except PagamentosStorageErro:
            abort(404)

    @app.get("/p/<token>/arquivo/<arquivo_id>/baixar")
    def baixar(token, arquivo_id):
        perfil = _perfil(token)
        try:
            return redirect(url_temporaria(perfil, arquivo_id, download=True), code=302)
        except PagamentosStorageErro:
            abort(404)

    @app.post("/p/<token>/<pasta>/arquivo/<arquivo_id>/renomear")
    def renomear(token, pasta, arquivo_id):
        perfil = _perfil(token)
        try:
            renomear_arquivo(perfil, pasta, arquivo_id, request.form.get("nome") or "")
            flash("Arquivo renomeado.", "sucesso")
        except PagamentosStorageErro as exc:
            flash(str(exc), "erro")
        return redirect(url_for("arquivos", token=token, pasta=pasta))

    @app.post("/p/<token>/<pasta>/arquivo/<arquivo_id>/excluir")
    def excluir(token, pasta, arquivo_id):
        perfil = _perfil(token)
        try:
            excluir_arquivo(perfil, pasta, arquivo_id)
            flash("Arquivo excluído.", "sucesso")
        except PagamentosStorageErro as exc:
            flash(str(exc), "erro")
        return redirect(url_for("arquivos", token=token, pasta=pasta))

    @app.post("/p/<token>/contas_com_erro/arquivo/<arquivo_id>/reenviar")
    def reenviar(token, arquivo_id):
        perfil = _perfil(token)
        try:
            reenviar_arquivo_erro(perfil, arquivo_id, request.form.get("nome") or "")
            flash("Arquivo corrigido e devolvido à pasta de entrada.", "sucesso")
        except PagamentosStorageErro as exc:
            flash(str(exc), "erro")
        return redirect(url_for("arquivos", token=token, pasta="contas_com_erro"))

    return app


app = create_portal_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
