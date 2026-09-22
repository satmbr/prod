BEGIN;

ALTER TABLE fornecedor_orcamentos
    ADD COLUMN IF NOT EXISTS revisao_tipo VARCHAR(20),
    ADD COLUMN IF NOT EXISTS revisao_observacao TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='ck_fornecedor_orcamento_revisao_tipo'
    ) THEN
        ALTER TABLE fornecedor_orcamentos
            ADD CONSTRAINT ck_fornecedor_orcamento_revisao_tipo
            CHECK (revisao_tipo IS NULL OR revisao_tipo IN ('DESCONTO','AJUSTE_ADMIN'));
    END IF;
END $$;

ALTER TABLE fornecedor_orcamento_itens
    ADD COLUMN IF NOT EXISTS valor_unitario_proposto_admin NUMERIC(14,2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname='ck_fornecedor_item_proposta_admin'
    ) THEN
        ALTER TABLE fornecedor_orcamento_itens
            ADD CONSTRAINT ck_fornecedor_item_proposta_admin
            CHECK (valor_unitario_proposto_admin IS NULL OR valor_unitario_proposto_admin >= 0);
    END IF;
END $$;

UPDATE fornecedor_orcamentos
SET revisao_tipo='DESCONTO',
    revisao_observacao=COALESCE(NULLIF(revisao_observacao,''),NULLIF(motivo_decisao,''),
      'Solicitamos uma melhoria nos valores apresentados.'),
    motivo_decisao=NULL
WHERE status='REVISAO_SOLICITADA' AND revisao_tipo IS NULL;

UPDATE fornecedor_orcamentos
SET motivo_decisao=NULL
WHERE status='REVISAO_SOLICITADA'
  AND revisao_tipo IS NOT NULL
  AND motivo_decisao IS NOT DISTINCT FROM revisao_observacao;

COMMIT;
