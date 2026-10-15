BEGIN;
ALTER TABLE financeiro3_pagamento_contas
  ADD COLUMN IF NOT EXISTS repetida_em TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS repetida_por INTEGER REFERENCES usuarios(id);
COMMIT;
