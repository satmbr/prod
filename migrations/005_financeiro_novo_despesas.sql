BEGIN;

CREATE TABLE IF NOT EXISTS financeiro3_despesas (
    id BIGSERIAL PRIMARY KEY,
    descricao VARCHAR(220) NOT NULL,
    fornecedor_id BIGINT NOT NULL REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    favorecido_id BIGINT REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    centro_custo_id BIGINT NOT NULL REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    categoria_id BIGINT NOT NULL REFERENCES financeiro3_categorias(id) ON DELETE RESTRICT,
    moeda_id BIGINT NOT NULL REFERENCES financeiro3_moedas(id) ON DELETE RESTRICT,
    numero_documento VARCHAR(80),
    data_emissao DATE NOT NULL,
    data_competencia DATE NOT NULL,
    data_vencimento DATE NOT NULL,
    valor_total NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (valor_total >= 0),
    status VARCHAR(24) NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN (
        'RASCUNHO', 'EM_APROVACAO', 'APROVADA', 'REJEITADA',
        'PAGAMENTO_PARCIAL', 'PAGA', 'CANCELADA'
    )),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    enviado_em TIMESTAMPTZ,
    aprovado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    aprovado_em TIMESTAMPTZ,
    pago_em TIMESTAMPTZ,
    cancelado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    cancelado_em TIMESTAMPTZ,
    motivo_cancelamento TEXT,
    CHECK (data_vencimento >= data_emissao)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_despesas_status_vencimento
    ON financeiro3_despesas (status, data_vencimento, id DESC);
CREATE INDEX IF NOT EXISTS ix_financeiro3_despesas_fornecedor
    ON financeiro3_despesas (fornecedor_id, id DESC);

CREATE TABLE IF NOT EXISTS financeiro3_despesa_itens (
    id BIGSERIAL PRIMARY KEY,
    despesa_id BIGINT NOT NULL REFERENCES financeiro3_despesas(id) ON DELETE RESTRICT,
    descricao VARCHAR(220) NOT NULL,
    quantidade NUMERIC(15, 4) NOT NULL CHECK (quantidade > 0),
    valor_unitario NUMERIC(18, 4) NOT NULL CHECK (valor_unitario >= 0),
    valor_total NUMERIC(18, 2) GENERATED ALWAYS AS
        (ROUND(quantidade * valor_unitario, 2)) STORED,
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO', 'REMOVIDO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    removido_em TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_despesa_itens_despesa
    ON financeiro3_despesa_itens (despesa_id, status, id);

CREATE OR REPLACE FUNCTION financeiro3_atualizar_total_despesa()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    alvo BIGINT;
BEGIN
    alvo := COALESCE(NEW.despesa_id, OLD.despesa_id);
    UPDATE financeiro3_despesas
    SET valor_total = COALESCE((
            SELECT SUM(valor_total)
            FROM financeiro3_despesa_itens
            WHERE despesa_id = alvo AND status = 'ATIVO'
        ), 0),
        atualizado_em = NOW()
    WHERE id = alvo;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_despesa_total ON financeiro3_despesa_itens;
CREATE TRIGGER tg_financeiro3_despesa_total
AFTER INSERT OR UPDATE OR DELETE ON financeiro3_despesa_itens
FOR EACH ROW EXECUTE FUNCTION financeiro3_atualizar_total_despesa();

CREATE TABLE IF NOT EXISTS financeiro3_despesa_decisoes (
    id BIGSERIAL PRIMARY KEY,
    despesa_id BIGINT NOT NULL REFERENCES financeiro3_despesas(id) ON DELETE RESTRICT,
    acao VARCHAR(20) NOT NULL CHECK (acao IN ('ENVIO', 'APROVACAO', 'REJEICAO', 'CANCELAMENTO')),
    status_anterior VARCHAR(24) NOT NULL,
    status_novo VARCHAR(24) NOT NULL,
    justificativa TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_despesa_decisoes_despesa
    ON financeiro3_despesa_decisoes (despesa_id, criado_em DESC);

CREATE TABLE IF NOT EXISTS financeiro3_despesa_pagamentos (
    id BIGSERIAL PRIMARY KEY,
    despesa_id BIGINT NOT NULL REFERENCES financeiro3_despesas(id) ON DELETE RESTRICT,
    conta_id BIGINT NOT NULL REFERENCES financeiro3_contas(id) ON DELETE RESTRICT,
    data_pagamento DATE NOT NULL,
    valor NUMERIC(18, 2) NOT NULL CHECK (valor > 0),
    forma VARCHAR(20) NOT NULL CHECK (forma IN (
        'PIX', 'TRANSFERENCIA', 'BOLETO', 'CARTAO', 'DINHEIRO', 'OUTRA'
    )),
    referencia VARCHAR(120),
    observacoes TEXT,
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO', 'ESTORNADO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_despesa_pagamentos_despesa
    ON financeiro3_despesa_pagamentos (despesa_id, status, data_pagamento);

UPDATE financeiro3_configuracao
SET versao_schema = 3, atualizado_em = NOW()
WHERE id = 1 AND versao_schema < 3;

COMMIT;
