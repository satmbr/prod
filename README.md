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
com valor; comprovantes são opcionais e, quando enviados, imagens e PDFs são
armazenados como PDF canônico privado.

O ciclo de missões é criado pela migration
`migrations/006_financeiro_novo_om_rd.sql`, complementado pelas migrations
posteriores. OM e RD são documentos independentes; ambas podem ser importadas
para Despesas sem duplicar o pagamento registrado na origem.

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

`migrations/010_financeiro_novo_om_lote_rd_independente.sql` acrescenta o
centro de custo por linha da OM e restaura a criação independente de RDs com
número, matrícula, responsável e período próprios. A tela da OM permite montar
e salvar várias linhas em uma transação e verifica possíveis duplicidades por
data e valor antes da gravação.

`migrations/011_financeiro_novo_fluxo_documentos_previsao.sql` consolida a
relação independente entre OM, RD, Despesas, Reembolsos e Notas de Débito.
`migrations/012_financeiro_novo_empresas.sql` separa Despesas e Notas de
Débito em MATISA, PRUMO e PRUMAT. Registros anteriores e importações de OM/RD
permanecem MATISA; uma Nota de Débito só aceita despesas da mesma empresa.

`migrations/013_financeiro_novo_pagamento_despesa_sem_conta.sql` torna a conta
opcional no pagamento de Despesas, coerente com a ausência de controle de
tesouraria no módulo. O cancelamento de Despesa permanece auditado por usuário
e data, sem exigir motivo.

Uma OM aprovada pode ser importada pela listagem de Despesas Matisa. Ela ocupa
um único registro na lista, enquanto suas linhas mantêm vínculo com os itens e
recibos originais da OM. As linhas vinculadas podem ser selecionadas em Notas
de Débito sem copiar os arquivos no volume.

<!-- Verificação de publicação: 2026-08-18 -->

## Perfil de Pagamentos e Google Drive

O painel `/financeiro-novo/perfil-pagamentos` mantém perfis e contas isolados
dos demais lançamentos do Financeiro Novo. Configure a credencial JSON da conta
de serviço em `GOOGLE_SERVICE_ACCOUNT_JSON` (JSON puro ou Base64). Nunca grave
essa credencial no repositório.

Cada perfil aponta para uma pasta raiz compartilhada com o e-mail da conta de
serviço. A primeira sincronização cria `novas_contas`, `contas_controladas`,
`contas_quitadas`, `comprovantes` e `contas_com_erro`. O nome de entrada é:

```text
100,50 25.09.2026 28.09.2026 manutencao veicular ABERTA PENDENTE.pdf
```

Somente valor e descrição são obrigatórios. As formas reduzidas também são
aceitas:

```text
254,00 hospedagem.jpeg
254,00 01.09.2026 abastecimento.jpeg
```

Datas ausentes usam a data atual de São Paulo. Status ausentes usam `ABERTA` e `PENDENTE`.

Para o processamento diário das 23:00 em America/Sao_Paulo, crie no Railway um
serviço Cron usando este repositório, comando `python sync_pagamentos.py` e
agenda `0 2 * * *` (Railway usa UTC). A execução é idempotente pelo ID do arquivo
no Drive e pode ser repetida manualmente pelo painel.
