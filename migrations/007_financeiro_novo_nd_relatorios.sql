BEGIN;

CREATE TABLE IF NOT EXISTS financeiro3_clientes (
    id BIGSERIAL PRIMARY KEY,
    tipo_pessoa VARCHAR(10) NOT NULL CHECK (tipo_pessoa IN ('FISICA','JURIDICA')),
    nome_razao VARCHAR(180) NOT NULL,
    nome_fantasia VARCHAR(180),
    documento VARCHAR(14) UNIQUE,
    email VARCHAR(180),
    telefone VARCHAR(30),
    endereco_cobranca VARCHAR(500),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (documento IS NULL OR length(documento) IN (11,14))
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_clientes_nome ON financeiro3_clientes(nome_razao);

CREATE TABLE IF NOT EXISTS financeiro3_notas_debito (
    id BIGSERIAL PRIMARY KEY,
    cliente_id BIGINT NOT NULL REFERENCES financeiro3_clientes(id) ON DELETE RESTRICT,
    centro_custo_id BIGINT NOT NULL REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    moeda_id BIGINT NOT NULL REFERENCES financeiro3_moedas(id) ON DELETE RESTRICT,
    descricao VARCHAR(250) NOT NULL,
    data_emissao DATE NOT NULL,
    data_vencimento DATE NOT NULL,
    valor_total NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (valor_total >= 0),
    status VARCHAR(24) NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN (
        'RASCUNHO','EM_APROVACAO','EMITIDA','RECEBIMENTO_PARCIAL',
        'RECEBIDA','REJEITADA','CANCELADA'
    )),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    emitido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    emitido_em TIMESTAMPTZ,
    CHECK (data_vencimento >= data_emissao)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_nd_status_vencimento
    ON financeiro3_notas_debito(status,data_vencimento,id DESC);

CREATE TABLE IF NOT EXISTS financeiro3_nd_itens (
    id BIGSERIAL PRIMARY KEY,
    nota_debito_id BIGINT NOT NULL REFERENCES financeiro3_notas_debito(id) ON DELETE RESTRICT,
    descricao VARCHAR(220) NOT NULL,
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    despesa_id BIGINT REFERENCES financeiro3_despesas(id) ON DELETE RESTRICT,
    rd_id BIGINT REFERENCES financeiro3_rds(id) ON DELETE RESTRICT,
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO','REMOVIDO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    removido_em TIMESTAMPTZ,
    CHECK (num_nonnulls(despesa_id,rd_id) <= 1)
);

CREATE OR REPLACE FUNCTION financeiro3_atualizar_total_nd()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE alvo BIGINT;
BEGIN
    alvo := COALESCE(NEW.nota_debito_id,OLD.nota_debito_id);
    UPDATE financeiro3_notas_debito
    SET valor_total=COALESCE((SELECT SUM(valor) FROM financeiro3_nd_itens
        WHERE nota_debito_id=alvo AND status='ATIVO'),0), atualizado_em=NOW()
    WHERE id=alvo;
    RETURN COALESCE(NEW,OLD);
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_nd_total ON financeiro3_nd_itens;
CREATE TRIGGER tg_financeiro3_nd_total
AFTER INSERT OR UPDATE OR DELETE ON financeiro3_nd_itens
FOR EACH ROW EXECUTE FUNCTION financeiro3_atualizar_total_nd();

CREATE TABLE IF NOT EXISTS financeiro3_nd_decisoes (
    id BIGSERIAL PRIMARY KEY,
    nota_debito_id BIGINT NOT NULL REFERENCES financeiro3_notas_debito(id) ON DELETE RESTRICT,
    acao VARCHAR(20) NOT NULL CHECK (acao IN ('ENVIO','EMISSAO','REJEICAO','CANCELAMENTO','RECEBIMENTO')),
    status_anterior VARCHAR(24) NOT NULL,
    status_novo VARCHAR(24) NOT NULL,
    justificativa TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_nd_recebimentos (
    id BIGSERIAL PRIMARY KEY,
    nota_debito_id BIGINT NOT NULL REFERENCES financeiro3_notas_debito(id) ON DELETE RESTRICT,
    conta_id BIGINT NOT NULL REFERENCES financeiro3_contas(id) ON DELETE RESTRICT,
    data_recebimento DATE NOT NULL,
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    forma VARCHAR(20) NOT NULL CHECK (forma IN ('PIX','TRANSFERENCIA','BOLETO','CARTAO','DINHEIRO','OUTRA')),
    referencia VARCHAR(120),
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO','ESTORNADO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_conciliacoes (
    id BIGSERIAL PRIMARY KEY,
    origem_tipo VARCHAR(24) NOT NULL CHECK (origem_tipo IN ('DESPESA_PAGAMENTO','RD_ACERTO','ND_RECEBIMENTO')),
    origem_id BIGINT NOT NULL,
    conta_id BIGINT NOT NULL REFERENCES financeiro3_contas(id) ON DELETE RESTRICT,
    movimento VARCHAR(7) NOT NULL CHECK (movimento IN ('DEBITO','CREDITO')),
    data_movimento DATE NOT NULL,
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    referencia_extrato VARCHAR(160) NOT NULL,
    observacoes TEXT,
    conciliado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    conciliado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (origem_tipo,origem_id)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_conciliacoes_conta_data
    ON financeiro3_conciliacoes(conta_id,data_movimento DESC);

UPDATE financeiro3_configuracao
SET versao_schema=5, atualizado_em=NOW()
WHERE id=1 AND versao_schema < 5;

COMMIT;
