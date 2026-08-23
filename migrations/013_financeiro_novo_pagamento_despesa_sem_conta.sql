BEGIN;

-- O pagamento da despesa registra o fato financeiro sem exigir uma conta,
-- pois o módulo não controla tesouraria ou movimentação bancária.
ALTER TABLE financeiro3_despesa_pagamentos
    ALTER COLUMN conta_id DROP NOT NULL;

UPDATE financeiro3_configuracao
SET versao_schema=11, atualizado_em=NOW()
WHERE id=1 AND versao_schema<11;

COMMIT;
