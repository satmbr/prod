BEGIN;

ALTER TABLE financeiro3_pagamento_perfis
    ADD COLUMN IF NOT EXISTS telegram_token VARCHAR(64),
    ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT,
    ADD COLUMN IF NOT EXISTS telegram_chat_nome VARCHAR(200),
    ADD COLUMN IF NOT EXISTS telegram_modo VARCHAR(16) NOT NULL DEFAULT 'NOVAS'
        CHECK (telegram_modo IN ('NOVAS','COMPROVANTES'));

UPDATE financeiro3_pagamento_perfis
SET telegram_token = replace(gen_random_uuid()::text, '-', '')
WHERE telegram_token IS NULL;

ALTER TABLE financeiro3_pagamento_perfis
    ALTER COLUMN telegram_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_telegram_token
    ON financeiro3_pagamento_perfis (telegram_token);
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_telegram_chat
    ON financeiro3_pagamento_perfis (telegram_chat_id)
    WHERE telegram_chat_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_telegram_updates (
    update_id BIGINT PRIMARY KEY,
    chat_id BIGINT,
    status VARCHAR(12) NOT NULL DEFAULT 'INICIADO'
        CHECK (status IN ('INICIADO','CONCLUIDO','ERRO')),
    mensagem TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
