BEGIN;

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_telegram_chats (
    chat_id BIGINT PRIMARY KEY,
    perfil_id BIGINT NOT NULL REFERENCES financeiro3_pagamento_perfis(id) ON DELETE CASCADE,
    chat_nome VARCHAR(200) NOT NULL,
    modo VARCHAR(16) NOT NULL DEFAULT 'NOVAS'
        CHECK (modo IN ('NOVAS','COMPROVANTES')),
    vinculado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_telegram_chats_perfil
    ON financeiro3_pagamento_telegram_chats (perfil_id,chat_nome,chat_id);

INSERT INTO financeiro3_pagamento_telegram_chats
    (chat_id,perfil_id,chat_nome,modo)
SELECT telegram_chat_id,id,COALESCE(telegram_chat_nome,telegram_chat_id::text),telegram_modo
FROM financeiro3_pagamento_perfis
WHERE telegram_chat_id IS NOT NULL
ON CONFLICT (chat_id) DO UPDATE SET
    perfil_id=EXCLUDED.perfil_id,
    chat_nome=EXCLUDED.chat_nome,
    modo=EXCLUDED.modo,
    atualizado_em=NOW();

COMMIT;
