BEGIN;

DROP INDEX IF EXISTS ux_financeiro3_pagamento_perfil_gmail;

ALTER TABLE financeiro3_pagamento_perfis
    ALTER COLUMN gmail DROP NOT NULL;

UPDATE financeiro3_pagamento_perfis
SET gmail=NULL,atualizado_em=NOW()
WHERE gmail IS NOT NULL;

COMMIT;
