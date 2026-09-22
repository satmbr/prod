BEGIN;

INSERT INTO permissoes (modulo, acao, descricao)
VALUES
    ('fornecedores', 'visualizar', 'Visualizar fornecedores, solicitações e orçamentos'),
    ('fornecedores', 'administrar', 'Cadastrar fornecedores e criar solicitações de serviço'),
    ('fornecedores', 'aprovar', 'Revisar, rejeitar e aprovar orçamentos de fornecedores'),
    ('fornecedores', 'fechar', 'Acompanhar execução e fechar serviços de fornecedores')
ON CONFLICT (modulo, acao) DO UPDATE SET descricao=EXCLUDED.descricao;

CREATE TABLE IF NOT EXISTS fornecedores (
    id BIGSERIAL PRIMARY KEY,
    razao_social VARCHAR(200) NOT NULL,
    nome_fantasia VARCHAR(160),
    cnpj VARCHAR(18),
    contato_nome VARCHAR(160),
    email VARCHAR(200),
    telefone VARCHAR(40),
    endereco TEXT,
    observacoes TEXT,
    portal_token VARCHAR(64) NOT NULL UNIQUE DEFAULT replace(gen_random_uuid()::text, '-', ''),
    portal_ativo BOOLEAN NOT NULL DEFAULT FALSE,
    ultimo_acesso_em TIMESTAMPTZ,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fornecedores_cnpj
    ON fornecedores (regexp_replace(cnpj, '\\D', '', 'g')) WHERE cnpj IS NOT NULL;

CREATE SEQUENCE IF NOT EXISTS fornecedor_solicitacao_numero_seq START WITH 1;

CREATE TABLE IF NOT EXISTS fornecedor_solicitacoes (
    id BIGSERIAL PRIMARY KEY,
    numero VARCHAR(24) NOT NULL UNIQUE DEFAULT (
        'SS-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('fornecedor_solicitacao_numero_seq')::text, 6, '0')
    ),
    titulo VARCHAR(200) NOT NULL,
    descricao TEXT NOT NULL,
    local_servico VARCHAR(240),
    prazo_orcamento DATE,
    previsao_execucao DATE,
    status VARCHAR(28) NOT NULL DEFAULT 'RASCUNHO'
        CHECK (status IN ('RASCUNHO','ENVIADA','ORCAMENTO_RECEBIDO','REVISAO_SOLICITADA',
          'APROVADA','REJEITADA','EM_EXECUCAO','AGUARDANDO_FECHAMENTO','FECHADA','CANCELADA')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fechado_em TIMESTAMPTZ,
    fechado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS fornecedor_solicitacao_destinos (
    id BIGSERIAL PRIMARY KEY,
    solicitacao_id BIGINT NOT NULL REFERENCES fornecedor_solicitacoes(id) ON DELETE CASCADE,
    fornecedor_id BIGINT NOT NULL REFERENCES fornecedores(id) ON DELETE RESTRICT,
    status VARCHAR(28) NOT NULL DEFAULT 'AGUARDANDO_ORCAMENTO'
        CHECK (status IN ('AGUARDANDO_ORCAMENTO','ORCAMENTO_RECEBIDO','REVISAO_SOLICITADA',
          'APROVADO','REJEITADO','ENCERRADO','EM_EXECUCAO','AGUARDANDO_FECHAMENTO','FECHADO')),
    visualizado_em TIMESTAMPTZ,
    respondido_em TIMESTAMPTZ,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (solicitacao_id, fornecedor_id)
);

CREATE TABLE IF NOT EXISTS fornecedor_orcamentos (
    id BIGSERIAL PRIMARY KEY,
    destino_id BIGINT NOT NULL REFERENCES fornecedor_solicitacao_destinos(id) ON DELETE CASCADE,
    versao INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'ENVIADO'
        CHECK (status IN ('ENVIADO','REVISAO_SOLICITADA','APROVADO','REJEITADO','SUBSTITUIDO')),
    observacoes_fornecedor TEXT,
    subtotal_original NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (subtotal_original >= 0),
    subtotal_ajustado NUMERIC(14,2),
    bdi_percentual NUMERIC(7,4) NOT NULL DEFAULT 0 CHECK (bdi_percentual >= 0),
    bdi_valor NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (bdi_valor >= 0),
    total_aprovado NUMERIC(14,2),
    motivo_decisao TEXT,
    decidido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    decidido_em TIMESTAMPTZ,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (destino_id, versao)
);

CREATE TABLE IF NOT EXISTS fornecedor_orcamento_itens (
    id BIGSERIAL PRIMARY KEY,
    orcamento_id BIGINT NOT NULL REFERENCES fornecedor_orcamentos(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL,
    descricao TEXT NOT NULL,
    unidade VARCHAR(20) NOT NULL DEFAULT 'UN',
    quantidade NUMERIC(14,4) NOT NULL CHECK (quantidade > 0),
    valor_unitario_original NUMERIC(14,2) NOT NULL CHECK (valor_unitario_original >= 0),
    valor_unitario_ajustado NUMERIC(14,2),
    CHECK (valor_unitario_ajustado IS NULL OR valor_unitario_ajustado >= valor_unitario_original),
    UNIQUE (orcamento_id, ordem)
);

CREATE TABLE IF NOT EXISTS fornecedor_arquivos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    solicitacao_id BIGINT NOT NULL REFERENCES fornecedor_solicitacoes(id) ON DELETE CASCADE,
    destino_id BIGINT REFERENCES fornecedor_solicitacao_destinos(id) ON DELETE CASCADE,
    orcamento_id BIGINT REFERENCES fornecedor_orcamentos(id) ON DELETE CASCADE,
    categoria VARCHAR(24) NOT NULL
        CHECK (categoria IN ('SOLICITACAO','ORCAMENTO','EVIDENCIA','NOTA_FISCAL','FECHAMENTO')),
    origem VARCHAR(12) NOT NULL CHECK (origem IN ('SISTEMA','FORNECEDOR')),
    nome_original VARCHAR(500) NOT NULL,
    caminho_relativo VARCHAR(700) NOT NULL UNIQUE,
    mime VARCHAR(100) NOT NULL DEFAULT 'application/pdf',
    tamanho BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    enviado_por_usuario INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    enviado_por_fornecedor BIGINT REFERENCES fornecedores(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fornecedor_eventos (
    id BIGSERIAL PRIMARY KEY,
    solicitacao_id BIGINT NOT NULL REFERENCES fornecedor_solicitacoes(id) ON DELETE CASCADE,
    destino_id BIGINT REFERENCES fornecedor_solicitacao_destinos(id) ON DELETE SET NULL,
    tipo VARCHAR(40) NOT NULL,
    descricao TEXT NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    fornecedor_id BIGINT REFERENCES fornecedores(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_fornecedor_solicitacoes_status
    ON fornecedor_solicitacoes(status, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_fornecedor_destinos_fornecedor
    ON fornecedor_solicitacao_destinos(fornecedor_id, status, atualizado_em DESC);
CREATE INDEX IF NOT EXISTS ix_fornecedor_orcamentos_destino
    ON fornecedor_orcamentos(destino_id, versao DESC);
CREATE INDEX IF NOT EXISTS ix_fornecedor_arquivos_solicitacao
    ON fornecedor_arquivos(solicitacao_id, categoria, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_fornecedor_eventos_solicitacao
    ON fornecedor_eventos(solicitacao_id, criado_em DESC);

COMMIT;
