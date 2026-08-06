BEGIN;

-- Cada despesa da OM pode ser apropriada em um centro de custo próprio.
ALTER TABLE financeiro3_om_itens
    ADD COLUMN IF NOT EXISTS centro_custo_id BIGINT REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT;

UPDATE financeiro3_om_itens i
SET centro_custo_id=o.centro_custo_id
FROM financeiro3_oms o
WHERE o.id=i.om_id AND i.centro_custo_id IS NULL;

ALTER TABLE financeiro3_om_itens
    ALTER COLUMN centro_custo_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_itens_centro
    ON financeiro3_om_itens(centro_custo_id,data_despesa,id);

-- A RD volta a ser um documento independente, como no fluxo anterior.
ALTER TABLE financeiro3_rds
    ADD COLUMN IF NOT EXISTS numero_rd VARCHAR(80),
    ADD COLUMN IF NOT EXISTS matricula_responsavel VARCHAR(40);

UPDATE financeiro3_rds r
SET numero_rd=COALESCE(r.numero_rd,'OM-'||o.numero_om),
    matricula_responsavel=COALESCE(r.matricula_responsavel,o.matricula_favorecido)
FROM financeiro3_oms o
WHERE o.id=r.om_id AND (r.numero_rd IS NULL OR r.matricula_responsavel IS NULL);

UPDATE financeiro3_rds
SET numero_rd=COALESCE(numero_rd,'LEGADO-RD-'||LPAD(id::text,6,'0')),
    matricula_responsavel=COALESCE(matricula_responsavel,'NÃO INFORMADA')
WHERE numero_rd IS NULL OR matricula_responsavel IS NULL;

ALTER TABLE financeiro3_rds
    ALTER COLUMN numero_rd SET NOT NULL,
    ALTER COLUMN matricula_responsavel SET NOT NULL,
    ALTER COLUMN om_id DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_rds_numero
    ON financeiro3_rds(UPPER(numero_rd));

UPDATE financeiro3_configuracao
SET versao_schema=8, atualizado_em=NOW()
WHERE id=1 AND versao_schema < 8;

COMMIT;
