BEGIN;

ALTER TABLE financeiro3_pagamento_telegram_pendencias
    ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT,
    ADD COLUMN IF NOT EXISTS telegram_username VARCHAR(200),
    ADD COLUMN IF NOT EXISTS telegram_nome VARCHAR(240),
    ADD COLUMN IF NOT EXISTS telegram_enviado_em TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_telegram_envios (
    id BIGSERIAL PRIMARY KEY,
    perfil_id BIGINT NOT NULL REFERENCES financeiro3_pagamento_perfis(id) ON DELETE RESTRICT,
    drive_file_id VARCHAR(180) NOT NULL UNIQUE,
    pasta VARCHAR(32) NOT NULL CHECK (pasta IN ('novas_contas','comprovantes')),
    chat_id BIGINT NOT NULL,
    chat_nome VARCHAR(200),
    telegram_user_id BIGINT,
    telegram_username VARCHAR(200),
    telegram_nome VARCHAR(240) NOT NULL,
    update_id BIGINT,
    message_id BIGINT,
    nome_arquivo VARCHAR(500) NOT NULL,
    enviado_em TIMESTAMPTZ NOT NULL,
    registrado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_telegram_envios_perfil
    ON financeiro3_pagamento_telegram_envios(perfil_id,enviado_em DESC,id DESC);
CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_telegram_envios_chat
    ON financeiro3_pagamento_telegram_envios(chat_id,enviado_em DESC,id DESC);

COMMIT;
