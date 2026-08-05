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

## Financeiro Novo

O Financeiro Novo usa exclusivamente tabelas com prefixo `financeiro3_` e a
rota `/financeiro-novo`. Ele inicia vazio e não consulta, referencia ou altera
as tabelas `financeiro2_*` do módulo atual.

A fundação é criada pela migration
`migrations/003_financeiro_novo_fundacao.sql`. Os anexos do novo módulo têm
PDF como formato canônico: fotos são redimensionadas e convertidas, enquanto
PDFs são validados e otimizados. PDFs assinados são preservados para não
invalidar a assinatura. O PostgreSQL armazena somente metadados e referências
dos arquivos, nunca o conteúdo binário.
