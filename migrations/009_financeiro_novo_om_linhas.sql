BEGIN;

ALTER TABLE financeiro3_oms
    ADD COLUMN IF NOT EXISTS numero_om VARCHAR(80),
    ADD COLUMN IF NOT EXISTS matricula_favorecido VARCHAR(40),
    ADD COLUMN IF NOT EXISTS valor_total NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (valor_total >= 0),
    ADD COLUMN IF NOT EXISTS removido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS removido_em TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS motivo_remocao TEXT;

UPDATE financeiro3_oms
SET numero_om=COALESCE(numero_om,'LEGADO-'||LPAD(id::text,6,'0')),
    matricula_favorecido=COALESCE(matricula_favorecido,'NÃO INFORMADA')
WHERE numero_om IS NULL OR matricula_favorecido IS NULL;

ALTER TABLE financeiro3_oms
    ALTER COLUMN numero_om SET NOT NULL,
    ALTER COLUMN matricula_favorecido SET NOT NULL,
    ALTER COLUMN objetivo DROP NOT NULL,
    ALTER COLUMN origem DROP NOT NULL,
    ALTER COLUMN destino DROP NOT NULL,
    ALTER COLUMN data_inicio DROP NOT NULL,
    ALTER COLUMN data_fim DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_oms_numero_ativo
    ON financeiro3_oms(UPPER(numero_om)) WHERE removido_em IS NULL;

CREATE TABLE IF NOT EXISTS financeiro3_om_itens (
    id BIGSERIAL PRIMARY KEY,
    om_id BIGINT NOT NULL REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    data_despesa DATE NOT NULL,
    categoria_id BIGINT NOT NULL REFERENCES financeiro3_categorias(id) ON DELETE RESTRICT,
    fornecedor_id BIGINT REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    descricao VARCHAR(220) NOT NULL,
    numero_documento VARCHAR(80),
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    justificativa_sem_comprovante TEXT,
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO','REMOVIDO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    removido_em TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_itens_om
    ON financeiro3_om_itens(om_id,status,data_despesa,id);

CREATE OR REPLACE FUNCTION financeiro3_atualizar_total_om()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE alvo BIGINT;
BEGIN
    alvo := COALESCE(NEW.om_id,OLD.om_id);
    UPDATE financeiro3_oms
    SET valor_total=COALESCE((SELECT SUM(valor) FROM financeiro3_om_itens
        WHERE om_id=alvo AND status='ATIVO'),0), atualizado_em=NOW()
    WHERE id=alvo;
    RETURN COALESCE(NEW,OLD);
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_om_total ON financeiro3_om_itens;
CREATE TRIGGER tg_financeiro3_om_total
AFTER INSERT OR UPDATE OR DELETE ON financeiro3_om_itens
FOR EACH ROW EXECUTE FUNCTION financeiro3_atualizar_total_om();

-- A OM de homologação solicitada pelo usuário permanece auditável, mas some das telas.
UPDATE financeiro3_oms
SET removido_por=COALESCE(removido_por,atualizado_por,criado_por), removido_em=COALESCE(removido_em,NOW()),
    motivo_remocao=COALESCE(motivo_remocao,'Registro de teste removido durante homologação')
WHERE id=3 AND status='CANCELADA' AND LOWER(COALESCE(objetivo,''))='teste'
  AND NOT EXISTS(SELECT 1 FROM financeiro3_rds r WHERE r.om_id=financeiro3_oms.id)
  AND NOT EXISTS(SELECT 1 FROM financeiro3_anexos a WHERE a.entidade='OM'
    AND a.entidade_id=financeiro3_oms.id AND a.status='ATIVO');

UPDATE financeiro3_configuracao
SET versao_schema=7, atualizado_em=NOW()
WHERE id=1 AND versao_schema < 7;

COMMIT;
