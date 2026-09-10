BEGIN;

ALTER TABLE financeiro3_pagamento_telegram_pendencias
    ADD COLUMN IF NOT EXISTS status_reembolso VARCHAR(16),
    ADD COLUMN IF NOT EXISTS nome_destino VARCHAR(500);

ALTER TABLE financeiro3_pagamento_telegram_pendencias
    DROP CONSTRAINT IF EXISTS financeiro3_pagamento_telegram_pendencias_etapa_check;

ALTER TABLE financeiro3_pagamento_telegram_pendencias
    ADD CONSTRAINT financeiro3_pagamento_telegram_pendencias_etapa_check
    CHECK (etapa IN (
        'VALOR','DATA_DOCUMENTO','DATA_VENCIMENTO','DESCRICAO',
        'PAGAMENTO','REEMBOLSO','CONFIRMAR_DUPLICIDADE'
    ));

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_telegram_recibo_tokens (
    token_hash CHAR(64) PRIMARY KEY,
    arquivo_id UUID NOT NULL REFERENCES financeiro3_arquivos(id) ON DELETE CASCADE,
    om_item_id BIGINT REFERENCES financeiro3_om_itens(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    expira_em TIMESTAMPTZ NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_telegram_recibo_tokens_expira
    ON financeiro3_pagamento_telegram_recibo_tokens(expira_em);

COMMIT;
