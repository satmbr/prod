BEGIN;

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_telegram_pendencias (
    chat_id BIGINT PRIMARY KEY,
    perfil_id BIGINT NOT NULL REFERENCES financeiro3_pagamento_perfis(id) ON DELETE CASCADE,
    update_id_arquivo BIGINT NOT NULL,
    message_id_arquivo BIGINT,
    file_id TEXT NOT NULL,
    nome_original VARCHAR(500) NOT NULL,
    mime_type VARCHAR(120) NOT NULL,
    tamanho BIGINT NOT NULL DEFAULT 0 CHECK (tamanho >= 0),
    extensao VARCHAR(8) NOT NULL CHECK (extensao IN ('.pdf','.jpg','.jpeg','.png')),
    etapa VARCHAR(24) NOT NULL DEFAULT 'VALOR'
        CHECK (etapa IN ('VALOR','DATA_DOCUMENTO','DATA_VENCIMENTO','DESCRICAO',
                         'PAGAMENTO','REEMBOLSO')),
    valor NUMERIC(14,2),
    data_documento DATE,
    data_vencimento DATE,
    descricao VARCHAR(220),
    status_pagamento VARCHAR(16),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_telegram_pendencias_perfil
    ON financeiro3_pagamento_telegram_pendencias(perfil_id);

COMMIT;
