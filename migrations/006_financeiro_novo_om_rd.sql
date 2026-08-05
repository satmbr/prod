BEGIN;

CREATE TABLE IF NOT EXISTS financeiro3_oms (
    id BIGSERIAL PRIMARY KEY,
    solicitante_id BIGINT NOT NULL REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    centro_custo_id BIGINT NOT NULL REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    moeda_id BIGINT NOT NULL REFERENCES financeiro3_moedas(id) ON DELETE RESTRICT,
    objetivo VARCHAR(250) NOT NULL,
    origem VARCHAR(150) NOT NULL,
    destino VARCHAR(150) NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    valor_adiantamento NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (valor_adiantamento >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN (
        'RASCUNHO','EM_APROVACAO','APROVADA','REJEITADA','ENCERRADA','CANCELADA'
    )),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (data_fim >= data_inicio)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_oms_status_data
    ON financeiro3_oms(status, data_inicio DESC, id DESC);

CREATE TABLE IF NOT EXISTS financeiro3_om_decisoes (
    id BIGSERIAL PRIMARY KEY,
    om_id BIGINT NOT NULL REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    acao VARCHAR(20) NOT NULL CHECK (acao IN ('ENVIO','APROVACAO','REJEICAO','CANCELAMENTO','ENCERRAMENTO')),
    status_anterior VARCHAR(20) NOT NULL,
    status_novo VARCHAR(20) NOT NULL,
    justificativa TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_om_decisoes_om
    ON financeiro3_om_decisoes(om_id, criado_em DESC);

CREATE TABLE IF NOT EXISTS financeiro3_rds (
    id BIGSERIAL PRIMARY KEY,
    om_id BIGINT NOT NULL UNIQUE REFERENCES financeiro3_oms(id) ON DELETE RESTRICT,
    responsavel_id BIGINT NOT NULL REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    centro_custo_id BIGINT NOT NULL REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    moeda_id BIGINT NOT NULL REFERENCES financeiro3_moedas(id) ON DELETE RESTRICT,
    periodo_inicio DATE NOT NULL,
    periodo_fim DATE NOT NULL,
    valor_adiantamento NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (valor_adiantamento >= 0),
    valor_total NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (valor_total >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN (
        'RASCUNHO','EM_APROVACAO','APROVADA','REJEITADA','LIQUIDADA','CANCELADA'
    )),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (periodo_fim >= periodo_inicio)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_rds_status_periodo
    ON financeiro3_rds(status, periodo_fim DESC, id DESC);

CREATE TABLE IF NOT EXISTS financeiro3_rd_itens (
    id BIGSERIAL PRIMARY KEY,
    rd_id BIGINT NOT NULL REFERENCES financeiro3_rds(id) ON DELETE RESTRICT,
    data_despesa DATE NOT NULL,
    categoria_id BIGINT NOT NULL REFERENCES financeiro3_categorias(id) ON DELETE RESTRICT,
    fornecedor_id BIGINT REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    descricao VARCHAR(220) NOT NULL,
    numero_documento VARCHAR(80),
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO','REMOVIDO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    removido_em TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_rd_itens_rd
    ON financeiro3_rd_itens(rd_id, status, data_despesa, id);

CREATE OR REPLACE FUNCTION financeiro3_atualizar_total_rd()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE alvo BIGINT;
BEGIN
    alvo := COALESCE(NEW.rd_id, OLD.rd_id);
    UPDATE financeiro3_rds
    SET valor_total = COALESCE((SELECT SUM(valor) FROM financeiro3_rd_itens
        WHERE rd_id=alvo AND status='ATIVO'),0), atualizado_em=NOW()
    WHERE id=alvo;
    RETURN COALESCE(NEW,OLD);
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_rd_total ON financeiro3_rd_itens;
CREATE TRIGGER tg_financeiro3_rd_total
AFTER INSERT OR UPDATE OR DELETE ON financeiro3_rd_itens
FOR EACH ROW EXECUTE FUNCTION financeiro3_atualizar_total_rd();

CREATE TABLE IF NOT EXISTS financeiro3_rd_decisoes (
    id BIGSERIAL PRIMARY KEY,
    rd_id BIGINT NOT NULL REFERENCES financeiro3_rds(id) ON DELETE RESTRICT,
    acao VARCHAR(20) NOT NULL CHECK (acao IN ('ENVIO','APROVACAO','REJEICAO','CANCELAMENTO','LIQUIDACAO')),
    status_anterior VARCHAR(20) NOT NULL,
    status_novo VARCHAR(20) NOT NULL,
    justificativa TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_rd_acertos (
    id BIGSERIAL PRIMARY KEY,
    rd_id BIGINT NOT NULL UNIQUE REFERENCES financeiro3_rds(id) ON DELETE RESTRICT,
    tipo VARCHAR(12) NOT NULL CHECK (tipo IN ('REEMBOLSO','DEVOLUCAO')),
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    status VARCHAR(12) NOT NULL DEFAULT 'PENDENTE' CHECK (status IN ('PENDENTE','LIQUIDADO','CANCELADO')),
    conta_id BIGINT REFERENCES financeiro3_contas(id) ON DELETE RESTRICT,
    data_liquidacao DATE,
    forma VARCHAR(20) CHECK (forma IS NULL OR forma IN ('PIX','TRANSFERENCIA','BOLETO','CARTAO','DINHEIRO','OUTRA')),
    referencia VARCHAR(120),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    liquidado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    liquidado_em TIMESTAMPTZ
);

UPDATE financeiro3_configuracao
SET versao_schema=4, atualizado_em=NOW()
WHERE id=1 AND versao_schema < 4;

COMMIT;
