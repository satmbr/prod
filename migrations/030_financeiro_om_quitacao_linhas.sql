BEGIN;

ALTER TABLE financeiro3_om_itens
    ADD COLUMN IF NOT EXISTS quitada BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS quitada_pagamento_id BIGINT REFERENCES financeiro3_om_pagamentos(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS data_quitacao DATE,
    ADD COLUMN IF NOT EXISTS quitada_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_itens_quitacao
    ON financeiro3_om_itens (om_id,quitada,status,id);

CREATE TABLE IF NOT EXISTS financeiro3_om_movimentos (
    id BIGSERIAL PRIMARY KEY,
    om_id BIGINT NOT NULL REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    pagamento_id BIGINT NOT NULL UNIQUE REFERENCES financeiro3_om_pagamentos(id) ON DELETE RESTRICT,
    data_movimento DATE NOT NULL,
    centro_custo_id BIGINT NOT NULL REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    categoria_id BIGINT NOT NULL REFERENCES financeiro3_categorias(id) ON DELETE RESTRICT,
    descricao VARCHAR(220) NOT NULL,
    valor NUMERIC(18,2) NOT NULL CHECK (valor < 0),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_movimentos_om
    ON financeiro3_om_movimentos (om_id,id);

ALTER TABLE financeiro3_pagamento_contas
    ADD COLUMN IF NOT EXISTS reembolso_om_pagamento_id BIGINT
        REFERENCES financeiro3_om_pagamentos(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_contas_reembolso_om
    ON financeiro3_pagamento_contas (reembolso_om_pagamento_id)
    WHERE reembolso_om_pagamento_id IS NOT NULL;

INSERT INTO financeiro3_categorias (codigo,nome,natureza,descricao)
VALUES ('A_CLASSIFICAR','A classificar','DESPESA',
        'Categoria temporária usada em linhas replicadas e movimentos de pagamento da OM.')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO financeiro3_om_movimentos
  (om_id,pagamento_id,data_movimento,centro_custo_id,categoria_id,descricao,valor,criado_por)
SELECT o.id,pg.id,pg.data_pagamento,o.centro_custo_id,c.id,
       CASE WHEN pg.tipo='QUITACAO' THEN 'Quitação' ELSE 'Adiantamento' END
         ||' da OM '||o.numero_om,
       -pg.valor,COALESCE(pg.pago_por,pg.criado_por)
FROM financeiro3_om_pagamentos pg
JOIN financeiro3_oms o ON o.id=pg.om_id
JOIN financeiro3_categorias c ON c.codigo='A_CLASSIFICAR'
WHERE pg.status='PAGO'
ON CONFLICT (pagamento_id) DO NOTHING;

WITH despesas AS (
    SELECT i.id,i.om_id,
      SUM(i.valor) OVER (PARTITION BY i.om_id ORDER BY i.id) AS acumulado
    FROM financeiro3_om_itens i
    WHERE i.status='ATIVO'
), pagamentos AS (
    SELECT pg.id,pg.om_id,pg.data_pagamento,pg.pago_por,
      SUM(pg.valor) OVER (
        PARTITION BY pg.om_id ORDER BY pg.data_pagamento,pg.id
      ) AS acumulado
    FROM financeiro3_om_pagamentos pg
    WHERE pg.status='PAGO'
), alocacoes AS (
    SELECT d.id AS item_id,p.id AS pagamento_id,p.data_pagamento,p.pago_por
    FROM despesas d
    LEFT JOIN LATERAL (
        SELECT pg.id,pg.data_pagamento,pg.pago_por
        FROM pagamentos pg
        WHERE pg.om_id=d.om_id AND pg.acumulado>=d.acumulado
        ORDER BY pg.data_pagamento,pg.id
        LIMIT 1
    ) p ON TRUE
)
UPDATE financeiro3_om_itens i
SET quitada=(a.pagamento_id IS NOT NULL),
    quitada_pagamento_id=a.pagamento_id,
    data_quitacao=a.data_pagamento,
    quitada_por=a.pago_por
FROM alocacoes a
WHERE i.id=a.item_id;

UPDATE financeiro3_pagamento_contas c
SET status_reembolso='REEMBOLSADA',numero_om=o.numero_om,
    data_reembolso=i.data_quitacao,reembolso_por=i.quitada_por,
    reembolso_om_pagamento_id=i.quitada_pagamento_id,
    status_sincronizacao='PENDENTE',atualizado_em=NOW()
FROM financeiro3_om_itens i
JOIN financeiro3_oms o ON o.id=i.om_id
WHERE c.om_item_id=i.id AND c.om_id=o.id AND c.excluida_em IS NULL
  AND i.status='ATIVO' AND i.quitada;

COMMIT;
