BEGIN;

ALTER TABLE financeiro3_pagamento_contas
    ADD COLUMN IF NOT EXISTS om_id BIGINT REFERENCES financeiro3_oms(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS om_item_id BIGINT REFERENCES financeiro3_om_itens(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_contas_om
    ON financeiro3_pagamento_contas (om_id);

CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_contas_om_item
    ON financeiro3_pagamento_contas (om_item_id)
    WHERE om_item_id IS NOT NULL;

INSERT INTO financeiro3_categorias (codigo,nome,natureza,descricao)
VALUES ('A_CLASSIFICAR','A classificar','DESPESA',
        'Categoria temporária usada em linhas replicadas pelo Perfil de Pagamentos.')
ON CONFLICT (codigo) DO NOTHING;

COMMIT;
