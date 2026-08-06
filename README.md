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

Os cadastros-base são criados pela migration
`migrations/004_financeiro_novo_cadastros.sql`: fornecedores/favorecidos,
centros de custo, categorias, moedas e contas financeiras. Todos começam
vazios, são preenchidos manualmente e usam inativação em vez de exclusão
física, com alterações registradas na auditoria independente.

O fluxo de despesas é criado pela migration
`migrations/005_financeiro_novo_despesas.sql`. O total é sempre calculado a
partir dos itens, e os estados de rascunho, aprovação, pagamento e
cancelamento têm permissões independentes. O envio para aprovação exige item
e comprovante; imagens e PDFs são armazenados como PDF canônico privado.

O ciclo de missões é criado pela migration
`migrations/006_financeiro_novo_om_rd.sql`. Cada OM pode originar uma única
RD. Na aprovação da prestação, a diferença entre gastos e adiantamento gera
um reembolso, uma devolução ou a liquidação imediata quando o saldo é zero.

Notas de Débito, recebimentos e conciliações são criados pela migration
`migrations/007_financeiro_novo_nd_relatorios.sql`. Os relatórios consolidam
somente movimentos do novo módulo, apresentam previsão pelos saldos e
vencimentos e permitem exportação CSV. A conciliação é manual e exige uma
referência do extrato para cada movimento interno.

A rota administrativa `/financeiro-novo/homologacao` verifica em tempo real,
sem alterar dados, a versão do schema, cadastros mínimos, atribuição das
permissões e prontidão do armazenamento privado. No Railway, `UPLOAD_ROOT`
deve estar dentro do caminho informado por `RAILWAY_VOLUME_MOUNT_PATH`.

O complemento de reembolsos e previsão é criado pela migration
`migrations/008_financeiro_novo_reembolsos_previsao.sql`. Reembolsos avulsos
possuem itens, comprovantes normalizados, detecção de possível duplicidade,
aprovação segregada e pagamento auditado. A previsão dedicada consolida,
sem duplicar lançamentos, despesas, reembolsos, acertos de RD e Notas de
Débito por dia, semana, mês ou período personalizado.
`migrations/009_financeiro_novo_om_linhas.sql` atualiza a Ordem de Missão com
número informado, matrícula do favorecido, linhas de despesas, total derivado e
remoção lógica auditável. Os campos antigos de objetivo, adiantamento, origem e
destino deixam de fazer parte do fluxo da OM.
