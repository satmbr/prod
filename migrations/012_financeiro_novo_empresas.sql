BEGIN;

-- Todos os registros existentes pertencem ao processo MATISA. O DEFAULT
-- preserva essa classificação e mantém compatibilidade com integrações atuais.
ALTER TABLE financeiro3_despesas
    ADD COLUMN IF NOT EXISTS empresa VARCHAR(10) NOT NULL DEFAULT 'MATISA';
ALTER TABLE financeiro3_despesas DROP CONSTRAINT IF EXISTS financeiro3_despesa_empresa_ck;
ALTER TABLE financeiro3_despesas ADD CONSTRAINT financeiro3_despesa_empresa_ck
    CHECK (empresa IN ('MATISA','PRUMO','PRUMAT'));
ALTER TABLE financeiro3_despesas DROP CONSTRAINT IF EXISTS financeiro3_despesa_origem_empresa_ck;
ALTER TABLE financeiro3_despesas ADD CONSTRAINT financeiro3_despesa_origem_empresa_ck
    CHECK (origem_tipo='MANUAL' OR empresa='MATISA');
CREATE INDEX IF NOT EXISTS ix_financeiro3_despesas_empresa_status
    ON financeiro3_despesas(empresa,status,data_vencimento,id DESC);

ALTER TABLE financeiro3_notas_debito
    ADD COLUMN IF NOT EXISTS empresa VARCHAR(10) NOT NULL DEFAULT 'MATISA';
ALTER TABLE financeiro3_notas_debito DROP CONSTRAINT IF EXISTS financeiro3_nd_empresa_ck;
ALTER TABLE financeiro3_notas_debito ADD CONSTRAINT financeiro3_nd_empresa_ck
    CHECK (empresa IN ('MATISA','PRUMO','PRUMAT'));
CREATE INDEX IF NOT EXISTS ix_financeiro3_nd_empresa_status
    ON financeiro3_notas_debito(empresa,status,data_vencimento,id DESC);

CREATE OR REPLACE FUNCTION financeiro3_validar_empresa_nd_item()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    empresa_despesa VARCHAR(10);
    empresa_nota VARCHAR(10);
BEGIN
    IF NEW.despesa_item_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT d.empresa INTO empresa_despesa
    FROM financeiro3_despesa_itens i
    JOIN financeiro3_despesas d ON d.id=i.despesa_id
    WHERE i.id=NEW.despesa_item_id;
    SELECT empresa INTO empresa_nota
    FROM financeiro3_notas_debito WHERE id=NEW.nota_debito_id;
    IF empresa_despesa IS DISTINCT FROM empresa_nota THEN
        RAISE EXCEPTION 'A Despesa e a Nota de Débito devem pertencer à mesma empresa.';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_nd_item_empresa ON financeiro3_nd_itens;
CREATE TRIGGER tg_financeiro3_nd_item_empresa
BEFORE INSERT OR UPDATE OF nota_debito_id,despesa_item_id ON financeiro3_nd_itens
FOR EACH ROW EXECUTE FUNCTION financeiro3_validar_empresa_nd_item();

UPDATE financeiro3_configuracao SET versao_schema=10,atualizado_em=NOW()
WHERE id=1 AND versao_schema<10;

COMMIT;
