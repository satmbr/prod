BEGIN;

CREATE TABLE IF NOT EXISTS operacao_observacao (
    id BIGSERIAL PRIMARY KEY,
    data DATE NOT NULL,
    eh_id BIGINT NOT NULL REFERENCES entre_house(id) ON DELETE CASCADE,
    frente_id BIGINT NOT NULL REFERENCES frente_equipe(id) ON DELETE CASCADE,
    observacao TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_por BIGINT
);

CREATE INDEX IF NOT EXISTS ix_operacao_observacao_eh_data_frente
    ON operacao_observacao (eh_id, data DESC, frente_id);

COMMIT;
