# satmbr/prod

Stack: Flask + Gunicorn. Deploy no Railway.

## Execução local
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
set SECRET_KEY=uma-chave-aleatoria-longa
python app.py  # http://localhost:8080
```

## Variáveis de ambiente

- `DATABASE_URL`: conexão PostgreSQL.
- `SECRET_KEY`: obrigatória; use um valor aleatório longo.
- `UPLOAD_ROOT`: diretório persistente para anexos. No Railway, aponte para
  um volume montado, por exemplo `/data/uploads`.
- `MAX_CONTENT_LENGTH`: limite de upload em bytes (padrão: 20 MB).
- `SESSION_COOKIE_SECURE`: opcional; no Railway o padrão é habilitado.
