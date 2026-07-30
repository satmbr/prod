BEGIN;

ALTER TABLE frente_equipe
    ADD COLUMN IF NOT EXISTS codigo VARCHAR(40),
    ADD COLUMN IF NOT EXISTS ordem INTEGER,
    ADD COLUMN IF NOT EXISTS escopo VARCHAR(10) NOT NULL DEFAULT 'EH';

UPDATE frente_equipe
SET codigo = CASE id
        WHEN 1 THEN 'RENOVACAO'
        WHEN 2 THEN 'CARREGAMENTO_NOVO'
        WHEN 3 THEN 'REMOCAO_GRAMPOS'
        WHEN 4 THEN 'REMOCAO_GALOCHAS'
        WHEN 5 THEN 'DESCARREGAMENTO_VELHO'
        WHEN 6 THEN 'APLICACAO_GRAMPOS'
        WHEN 7 THEN 'DESCARREGAMENTO_NOVO'
        WHEN 8 THEN 'SEGREGACAO_BOM'
        WHEN 9 THEN 'SEGREGACAO_RUIM'
        ELSE codigo
    END,
    ordem = COALESCE(ordem, id::integer),
    escopo = CASE WHEN id IN (8, 9) THEN 'PATIO' ELSE 'EH' END
WHERE id BETWEEN 1 AND 9;

UPDATE frente_equipe
SET frente = CASE id
        WHEN 8 THEN '08 - Segregação_bom (reaproveitável)'
        WHEN 9 THEN '09 - Segregação_ruim (não aproveitável)'
        ELSE frente
    END
WHERE id IN (8, 9);

CREATE UNIQUE INDEX IF NOT EXISTS uq_frente_equipe_codigo
    ON frente_equipe (codigo)
    WHERE codigo IS NOT NULL;

CREATE TABLE IF NOT EXISTS operacao_eh_config (
    eh_id BIGINT PRIMARY KEY REFERENCES entre_house(id) ON DELETE CASCADE,
    meta_total NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (meta_total >= 0),
    produtividade_dia NUMERIC(14, 2) NOT NULL DEFAULT 850 CHECK (produtividade_dia > 0),
    data_inicio DATE,
    data_fim_planejada DATE,
    observacao TEXT,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por BIGINT
);

CREATE TABLE IF NOT EXISTS operacao_saldo_inicial (
    id BIGSERIAL PRIMARY KEY,
    eh_id BIGINT NOT NULL REFERENCES entre_house(id) ON DELETE CASCADE,
    data_referencia DATE NOT NULL,
    saldo_codigo VARCHAR(40) NOT NULL CHECK (
        saldo_codigo IN (
            'PULMAO_CHAO',
            'NOVOS_VAGOES',
            'GRAMPOS_ABERTOS',
            'GALOCHAS_ABERTAS',
            'PREGACAO_ABERTA',
            'VELHOS_VAGOES'
        )
    ),
    quantidade NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por BIGINT,
    UNIQUE (eh_id, data_referencia, saldo_codigo)
);

CREATE INDEX IF NOT EXISTS ix_operacao_saldo_inicial_eh_data
    ON operacao_saldo_inicial (eh_id, data_referencia DESC);

CREATE TABLE IF NOT EXISTS operacao_impacto (
    id BIGSERIAL PRIMARY KEY,
    data DATE NOT NULL,
    eh_id BIGINT NOT NULL REFERENCES entre_house(id) ON DELETE CASCADE,
    frente_id BIGINT REFERENCES frente_equipe(id) ON DELETE SET NULL,
    hora_inicio TIME,
    hora_fim TIME,
    minutos_perdidos INTEGER NOT NULL CHECK (minutos_perdidos >= 0),
    categoria VARCHAR(40) NOT NULL CHECK (
        categoria IN (
            'CLIMA',
            'INTERFERENCIA_OPERACIONAL',
            'EQUIPAMENTO',
            'LOGISTICA_MATERIAL',
            'MAO_DE_OBRA',
            'SEGURANCA',
            'MANUTENCAO',
            'OUTRO'
        )
    ),
    descricao TEXT NOT NULL,
    responsavel VARCHAR(160),
    providencia TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'ABERTO'
        CHECK (status IN ('ABERTO', 'EM_TRATAMENTO', 'RESOLVIDO')),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_por BIGINT
);

CREATE INDEX IF NOT EXISTS ix_operacao_impacto_eh_data
    ON operacao_impacto (eh_id, data DESC);

CREATE TABLE IF NOT EXISTS operacao_patio (
    id BIGSERIAL PRIMARY KEY,
    data DATE NOT NULL,
    patio VARCHAR(120) NOT NULL DEFAULT 'Pátio principal',
    classificacao VARCHAR(10) NOT NULL CHECK (classificacao IN ('BOM', 'RUIM')),
    quantidade NUMERIC(14, 2) NOT NULL CHECK (quantidade >= 0),
    origem_eh_id BIGINT REFERENCES entre_house(id) ON DELETE SET NULL,
    observacao TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_por BIGINT
);

CREATE INDEX IF NOT EXISTS ix_operacao_patio_data
    ON operacao_patio (data DESC);

COMMIT;
