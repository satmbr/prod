BEGIN;

ALTER TABLE financeiro3_pagamento_contas
    ADD COLUMN IF NOT EXISTS excluida_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS excluida_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS motivo_exclusao TEXT;

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_contas_ativas
    ON financeiro3_pagamento_contas(perfil_id,data_vencimento,id)
    WHERE excluida_em IS NULL;

COMMIT;
