BEGIN;

ALTER TABLE fornecedor_solicitacoes
    ADD COLUMN IF NOT EXISTS cancelamento_motivo TEXT,
    ADD COLUMN IF NOT EXISTS cancelamento_solicitado_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancelamento_solicitado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS cancelamento_decidido_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancelamento_decisao VARCHAR(12),
    ADD COLUMN IF NOT EXISTS cancelamento_resposta TEXT,
    ADD COLUMN IF NOT EXISTS status_antes_cancelamento VARCHAR(28);

ALTER TABLE fornecedor_solicitacoes
    DROP CONSTRAINT IF EXISTS fornecedor_solicitacoes_status_check;
ALTER TABLE fornecedor_solicitacoes
    DROP CONSTRAINT IF EXISTS ck_fornecedor_solicitacao_status;
ALTER TABLE fornecedor_solicitacoes
    ADD CONSTRAINT ck_fornecedor_solicitacao_status CHECK (status IN (
      'RASCUNHO','ENVIADA','ORCAMENTO_RECEBIDO','REVISAO_SOLICITADA','APROVADA',
      'REJEITADA','EM_EXECUCAO','AGUARDANDO_FECHAMENTO','FECHADA',
      'CANCELAMENTO_SOLICITADO','CANCELADA'
    ));

ALTER TABLE fornecedor_solicitacoes
    DROP CONSTRAINT IF EXISTS ck_fornecedor_cancelamento_decisao;
ALTER TABLE fornecedor_solicitacoes
    ADD CONSTRAINT ck_fornecedor_cancelamento_decisao
    CHECK (cancelamento_decisao IS NULL OR cancelamento_decisao IN ('ACEITO','RECUSADO'));

ALTER TABLE fornecedor_solicitacao_destinos
    DROP CONSTRAINT IF EXISTS fornecedor_solicitacao_destinos_status_check;
ALTER TABLE fornecedor_solicitacao_destinos
    DROP CONSTRAINT IF EXISTS ck_fornecedor_destino_status;
ALTER TABLE fornecedor_solicitacao_destinos
    ADD CONSTRAINT ck_fornecedor_destino_status CHECK (status IN (
      'AGUARDANDO_ORCAMENTO','ORCAMENTO_RECEBIDO','REVISAO_SOLICITADA','APROVADO',
      'REJEITADO','ENCERRADO','EM_EXECUCAO','AGUARDANDO_FECHAMENTO','FECHADO',
      'CANCELAMENTO_SOLICITADO','CANCELADO'
    ));

COMMIT;
