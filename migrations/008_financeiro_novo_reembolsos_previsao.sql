BEGIN;

-- Adiantamento da OM: registro operacional, sem conta, forma ou conciliacao.
ALTER TABLE financeiro3_oms
    ADD COLUMN IF NOT EXISTS data_pagamento_adiantamento DATE,
    ADD COLUMN IF NOT EXISTS adiantamento_registrado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS adiantamento_registrado_em TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS financeiro3_reembolsos (
    id BIGSERIAL PRIMARY KEY,
    favorecido_id BIGINT NOT NULL REFERENCES financeiro3_pessoas(id) ON DELETE RESTRICT,
    centro_custo_id BIGINT NOT NULL REFERENCES financeiro3_centros_custo(id) ON DELETE RESTRICT,
    moeda_id BIGINT NOT NULL REFERENCES financeiro3_moedas(id) ON DELETE RESTRICT,
    matricula VARCHAR(40),
    chave_pix VARCHAR(180),
    tipo_chave_pix VARCHAR(20) CHECK (tipo_chave_pix IS NULL OR tipo_chave_pix IN
        ('CPF','CNPJ','EMAIL','TELEFONE','ALEATORIA','OUTRA')),
    objetivo VARCHAR(250) NOT NULL,
    data_solicitacao DATE NOT NULL,
    data_prevista_pagamento DATE NOT NULL,
    valor_total NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (valor_total >= 0),
    status VARCHAR(24) NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN (
        'RASCUNHO','EM_APROVACAO','APROVADO','REJEITADO','PAGO','CANCELADO'
    )),
    observacoes TEXT,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    enviado_em TIMESTAMPTZ,
    aprovado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    aprovado_em TIMESTAMPTZ,
    cancelado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    cancelado_em TIMESTAMPTZ,
    motivo_cancelamento TEXT,
    CHECK (data_prevista_pagamento >= data_solicitacao)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_reembolsos_status_previsao
    ON financeiro3_reembolsos(status,data_prevista_pagamento,id DESC);

CREATE TABLE IF NOT EXISTS financeiro3_reembolso_itens (
    id BIGSERIAL PRIMARY KEY,
    reembolso_id BIGINT NOT NULL REFERENCES financeiro3_reembolsos(id) ON DELETE RESTRICT,
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

CREATE INDEX IF NOT EXISTS ix_financeiro3_reembolso_itens_reembolso
    ON financeiro3_reembolso_itens(reembolso_id,status,data_despesa,id);

CREATE OR REPLACE FUNCTION financeiro3_atualizar_total_reembolso()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE alvo BIGINT;
BEGIN
    alvo := COALESCE(NEW.reembolso_id,OLD.reembolso_id);
    UPDATE financeiro3_reembolsos
    SET valor_total=COALESCE((SELECT SUM(valor) FROM financeiro3_reembolso_itens
        WHERE reembolso_id=alvo AND status='ATIVO'),0), atualizado_em=NOW()
    WHERE id=alvo;
    RETURN COALESCE(NEW,OLD);
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_reembolso_total ON financeiro3_reembolso_itens;
CREATE TRIGGER tg_financeiro3_reembolso_total
AFTER INSERT OR UPDATE OR DELETE ON financeiro3_reembolso_itens
FOR EACH ROW EXECUTE FUNCTION financeiro3_atualizar_total_reembolso();

CREATE TABLE IF NOT EXISTS financeiro3_reembolso_decisoes (
    id BIGSERIAL PRIMARY KEY,
    reembolso_id BIGINT NOT NULL REFERENCES financeiro3_reembolsos(id) ON DELETE RESTRICT,
    acao VARCHAR(20) NOT NULL CHECK (acao IN
        ('ENVIO','APROVACAO','REJEICAO','PAGAMENTO','CANCELAMENTO')),
    status_anterior VARCHAR(24) NOT NULL,
    status_novo VARCHAR(24) NOT NULL,
    justificativa TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_reembolso_pagamentos (
    id BIGSERIAL PRIMARY KEY,
    reembolso_id BIGINT NOT NULL UNIQUE REFERENCES financeiro3_reembolsos(id) ON DELETE RESTRICT,
    data_pagamento DATE NOT NULL,
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    observacoes TEXT,
    status VARCHAR(10) NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO','ESTORNADO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

UPDATE financeiro3_configuracao
SET versao_schema=6, atualizado_em=NOW()
WHERE id=1 AND versao_schema < 6;

COMMIT;
