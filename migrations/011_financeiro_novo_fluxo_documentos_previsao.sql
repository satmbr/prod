BEGIN;

-- OM e RD são documentos independentes. A coluna permanece apenas para
-- compatibilidade física com a fundação já publicada, sempre sem valor.
UPDATE financeiro3_rds SET om_id=NULL WHERE om_id IS NOT NULL;
ALTER TABLE financeiro3_rds DROP CONSTRAINT IF EXISTS financeiro3_rds_independente_ck;
ALTER TABLE financeiro3_rds ADD CONSTRAINT financeiro3_rds_independente_ck CHECK (om_id IS NULL);

CREATE TABLE IF NOT EXISTS financeiro3_om_pagamentos (
    id BIGSERIAL PRIMARY KEY,
    om_id BIGINT NOT NULL REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    tipo VARCHAR(16) NOT NULL CHECK (tipo IN ('ADIANTAMENTO','QUITACAO')),
    data_prevista_pagamento DATE NOT NULL,
    data_pagamento DATE,
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    status VARCHAR(12) NOT NULL DEFAULT 'PREVISTO' CHECK (status IN ('PREVISTO','PAGO','CANCELADO')),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pago_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    pago_em TIMESTAMPTZ,
    cancelado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    cancelado_em TIMESTAMPTZ,
    motivo_cancelamento TEXT,
    CHECK ((status='PAGO' AND data_pagamento IS NOT NULL) OR (status<>'PAGO' AND data_pagamento IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_financeiro3_om_pagamentos_previsao
    ON financeiro3_om_pagamentos(status,data_prevista_pagamento,om_id);

CREATE TABLE IF NOT EXISTS financeiro3_rd_pagamentos (
    id BIGSERIAL PRIMARY KEY,
    rd_id BIGINT NOT NULL REFERENCES financeiro3_rds(id) ON DELETE RESTRICT,
    tipo VARCHAR(16) NOT NULL CHECK (tipo IN ('ADIANTAMENTO','QUITACAO')),
    data_prevista_pagamento DATE NOT NULL,
    data_pagamento DATE,
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    status VARCHAR(12) NOT NULL DEFAULT 'PREVISTO' CHECK (status IN ('PREVISTO','PAGO','CANCELADO')),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pago_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    pago_em TIMESTAMPTZ,
    cancelado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    cancelado_em TIMESTAMPTZ,
    motivo_cancelamento TEXT,
    CHECK ((status='PAGO' AND data_pagamento IS NOT NULL) OR (status<>'PAGO' AND data_pagamento IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_financeiro3_rd_pagamentos_previsao
    ON financeiro3_rd_pagamentos(status,data_prevista_pagamento,rd_id);

ALTER TABLE financeiro3_rd_acertos
    ADD COLUMN IF NOT EXISTS data_prevista_liquidacao DATE;

ALTER TABLE financeiro3_reembolsos
    ADD COLUMN IF NOT EXISTS forma_liquidacao VARCHAR(12) NOT NULL DEFAULT 'DIRETO',
    ADD COLUMN IF NOT EXISTS om_pagadora_id BIGINT REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS rd_pagadora_id BIGINT REFERENCES financeiro3_rds(id) ON DELETE RESTRICT;
ALTER TABLE financeiro3_reembolsos DROP CONSTRAINT IF EXISTS financeiro3_reembolso_liquidacao_ck;
ALTER TABLE financeiro3_reembolsos ADD CONSTRAINT financeiro3_reembolso_liquidacao_ck CHECK (
    (forma_liquidacao='DIRETO' AND om_pagadora_id IS NULL AND rd_pagadora_id IS NULL) OR
    (forma_liquidacao='OM' AND om_pagadora_id IS NOT NULL AND rd_pagadora_id IS NULL) OR
    (forma_liquidacao='RD' AND rd_pagadora_id IS NOT NULL AND om_pagadora_id IS NULL)
);

ALTER TABLE financeiro3_despesas
    ADD COLUMN IF NOT EXISTS origem_tipo VARCHAR(12) NOT NULL DEFAULT 'MANUAL',
    ADD COLUMN IF NOT EXISTS origem_om_id BIGINT REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS origem_rd_id BIGINT REFERENCES financeiro3_rds(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS origem_reembolso_id BIGINT REFERENCES financeiro3_reembolsos(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS paga_na_origem BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS importada_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS importada_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;
ALTER TABLE financeiro3_despesas DROP CONSTRAINT IF EXISTS financeiro3_despesa_origem_ck;
ALTER TABLE financeiro3_despesas ADD CONSTRAINT financeiro3_despesa_origem_ck CHECK (
    (origem_tipo='MANUAL' AND num_nonnulls(origem_om_id,origem_rd_id,origem_reembolso_id)=0) OR
    (origem_tipo='OM' AND origem_om_id IS NOT NULL AND num_nonnulls(origem_rd_id,origem_reembolso_id)=0) OR
    (origem_tipo='RD' AND origem_rd_id IS NOT NULL AND num_nonnulls(origem_om_id,origem_reembolso_id)=0) OR
    (origem_tipo='REEMBOLSO' AND origem_reembolso_id IS NOT NULL AND num_nonnulls(origem_om_id,origem_rd_id)=0)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_despesa_origem_om ON financeiro3_despesas(origem_om_id) WHERE origem_om_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_despesa_origem_rd ON financeiro3_despesas(origem_rd_id) WHERE origem_rd_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_despesa_origem_reembolso ON financeiro3_despesas(origem_reembolso_id) WHERE origem_reembolso_id IS NOT NULL;

ALTER TABLE financeiro3_despesa_itens
    ADD COLUMN IF NOT EXISTS centro_custo_id BIGINT REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS categoria_id BIGINT REFERENCES financeiro3_categorias(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS om_item_id BIGINT REFERENCES financeiro3_om_itens(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS rd_item_id BIGINT REFERENCES financeiro3_rd_itens(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS reembolso_item_id BIGINT REFERENCES financeiro3_reembolso_itens(id) ON DELETE RESTRICT;
UPDATE financeiro3_despesa_itens i SET centro_custo_id=d.centro_custo_id,categoria_id=d.categoria_id
FROM financeiro3_despesas d WHERE d.id=i.despesa_id AND (i.centro_custo_id IS NULL OR i.categoria_id IS NULL);
ALTER TABLE financeiro3_despesa_itens ALTER COLUMN centro_custo_id SET NOT NULL;
ALTER TABLE financeiro3_despesa_itens ALTER COLUMN categoria_id SET NOT NULL;
ALTER TABLE financeiro3_despesa_itens DROP CONSTRAINT IF EXISTS financeiro3_despesa_item_origem_ck;
ALTER TABLE financeiro3_despesa_itens ADD CONSTRAINT financeiro3_despesa_item_origem_ck
    CHECK (num_nonnulls(om_item_id,rd_item_id,reembolso_item_id)<=1);
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_despesa_item_om ON financeiro3_despesa_itens(om_item_id) WHERE om_item_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_despesa_item_rd ON financeiro3_despesa_itens(rd_item_id) WHERE rd_item_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_despesa_item_reembolso ON financeiro3_despesa_itens(reembolso_item_id) WHERE reembolso_item_id IS NOT NULL;

ALTER TABLE financeiro3_nd_itens
    ADD COLUMN IF NOT EXISTS despesa_item_id BIGINT REFERENCES financeiro3_despesa_itens(id) ON DELETE RESTRICT;
UPDATE financeiro3_nd_itens SET rd_id=NULL WHERE rd_id IS NOT NULL;
ALTER TABLE financeiro3_nd_itens DROP CONSTRAINT IF EXISTS financeiro3_nd_sem_rd_direta_ck;
ALTER TABLE financeiro3_nd_itens ADD CONSTRAINT financeiro3_nd_sem_rd_direta_ck CHECK (rd_id IS NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_nd_item_despesa_item_ativo
    ON financeiro3_nd_itens(despesa_item_id) WHERE despesa_item_id IS NOT NULL AND status='ATIVO';

UPDATE financeiro3_configuracao SET versao_schema=9,atualizado_em=NOW()
WHERE id=1 AND versao_schema<9;

COMMIT;
