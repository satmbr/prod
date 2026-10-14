BEGIN;

CREATE SEQUENCE IF NOT EXISTS financeiro3_om_linhas_ordem_seq;

ALTER TABLE financeiro3_om_itens
    ADD COLUMN IF NOT EXISTS ordem_registro BIGINT;

ALTER TABLE financeiro3_om_movimentos
    ADD COLUMN IF NOT EXISTS ordem_registro BIGINT;

WITH eventos AS (
    SELECT 'ITEM'::text AS origem,i.id,i.criado_em AS registrado_em
    FROM financeiro3_om_itens i
    UNION ALL
    SELECT 'MOVIMENTO',mv.id,COALESCE(pg.pago_em,pg.criado_em,mv.criado_em)
    FROM financeiro3_om_movimentos mv
    JOIN financeiro3_om_pagamentos pg ON pg.id=mv.pagamento_id
), ordenados AS (
    SELECT origem,id,
      ROW_NUMBER() OVER (
        ORDER BY registrado_em,
          CASE WHEN origem='ITEM' THEN 0 ELSE 1 END,
          id
      ) AS ordem
    FROM eventos
)
UPDATE financeiro3_om_itens i
SET ordem_registro=o.ordem
FROM ordenados o
WHERE o.origem='ITEM' AND o.id=i.id;

WITH eventos AS (
    SELECT 'ITEM'::text AS origem,i.id,i.criado_em AS registrado_em
    FROM financeiro3_om_itens i
    UNION ALL
    SELECT 'MOVIMENTO',mv.id,COALESCE(pg.pago_em,pg.criado_em,mv.criado_em)
    FROM financeiro3_om_movimentos mv
    JOIN financeiro3_om_pagamentos pg ON pg.id=mv.pagamento_id
), ordenados AS (
    SELECT origem,id,
      ROW_NUMBER() OVER (
        ORDER BY registrado_em,
          CASE WHEN origem='ITEM' THEN 0 ELSE 1 END,
          id
      ) AS ordem
    FROM eventos
)
UPDATE financeiro3_om_movimentos mv
SET ordem_registro=o.ordem
FROM ordenados o
WHERE o.origem='MOVIMENTO' AND o.id=mv.id;

WITH maior AS (
    SELECT GREATEST(
      COALESCE((SELECT MAX(ordem_registro) FROM financeiro3_om_itens),0),
      COALESCE((SELECT MAX(ordem_registro) FROM financeiro3_om_movimentos),0)
    ) AS valor
)
SELECT setval(
    'financeiro3_om_linhas_ordem_seq',
    GREATEST(valor,1),
    valor>0
)
FROM maior;

ALTER TABLE financeiro3_om_itens
    ALTER COLUMN ordem_registro SET DEFAULT nextval('financeiro3_om_linhas_ordem_seq'),
    ALTER COLUMN ordem_registro SET NOT NULL;

ALTER TABLE financeiro3_om_movimentos
    ALTER COLUMN ordem_registro SET DEFAULT nextval('financeiro3_om_linhas_ordem_seq'),
    ALTER COLUMN ordem_registro SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_itens_ordem
    ON financeiro3_om_itens (om_id,ordem_registro);

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_movimentos_ordem
    ON financeiro3_om_movimentos (om_id,ordem_registro);

COMMIT;
