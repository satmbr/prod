BEGIN;

-- Cadastros manuais e isolados do Financeiro Novo.

CREATE TABLE IF NOT EXISTS financeiro3_pessoas (
    id BIGSERIAL PRIMARY KEY,
    tipo_pessoa VARCHAR(10) NOT NULL CHECK (tipo_pessoa IN ('FISICA', 'JURIDICA')),
    nome_razao VARCHAR(180) NOT NULL,
    nome_fantasia VARCHAR(180),
    documento VARCHAR(14) UNIQUE,
    email VARCHAR(180),
    telefone VARCHAR(30),
    fornecedor BOOLEAN NOT NULL DEFAULT FALSE,
    favorecido BOOLEAN NOT NULL DEFAULT FALSE,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (fornecedor OR favorecido),
    CHECK (documento IS NULL OR length(documento) IN (11, 14))
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pessoas_nome
    ON financeiro3_pessoas (nome_razao);

CREATE TABLE IF NOT EXISTS financeiro3_centros_custo (
    id BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(30) NOT NULL UNIQUE,
    nome VARCHAR(150) NOT NULL,
    descricao VARCHAR(500),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_categorias (
    id BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(30) NOT NULL UNIQUE,
    nome VARCHAR(150) NOT NULL,
    natureza VARCHAR(10) NOT NULL DEFAULT 'DESPESA'
        CHECK (natureza IN ('DESPESA', 'RECEITA')),
    descricao VARCHAR(500),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_moedas (
    id BIGSERIAL PRIMARY KEY,
    codigo CHAR(3) NOT NULL UNIQUE,
    nome VARCHAR(80) NOT NULL,
    simbolo VARCHAR(10) NOT NULL,
    casas_decimais SMALLINT NOT NULL DEFAULT 2 CHECK (casas_decimais BETWEEN 0 AND 4),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS financeiro3_contas (
    id BIGSERIAL PRIMARY KEY,
    nome VARCHAR(150) NOT NULL,
    tipo VARCHAR(15) NOT NULL
        CHECK (tipo IN ('CAIXA', 'CORRENTE', 'POUPANCA', 'CARTAO', 'OUTRA')),
    banco VARCHAR(120),
    agencia VARCHAR(30),
    numero VARCHAR(50),
    moeda_id BIGINT NOT NULL REFERENCES financeiro3_moedas(id) ON DELETE RESTRICT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (nome, moeda_id)
);

UPDATE financeiro3_configuracao
SET versao_schema = 2,
    atualizado_em = NOW()
WHERE id = 1 AND versao_schema < 2;

COMMIT;
