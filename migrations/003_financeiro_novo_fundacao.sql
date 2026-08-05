BEGIN;

-- Financeiro Novo: fundacao isolada. Este arquivo nao consulta nem referencia
-- qualquer tabela do modulo financeiro anterior.

INSERT INTO permissoes (modulo, acao, descricao)
SELECT 'financeiro_novo', dados.acao, dados.descricao
FROM (
    VALUES
        ('visualizar', 'Visualizar o Financeiro Novo'),
        ('criar', 'Criar registros no Financeiro Novo'),
        ('editar', 'Editar registros no Financeiro Novo'),
        ('aprovar', 'Aprovar registros no Financeiro Novo'),
        ('pagar', 'Registrar pagamentos no Financeiro Novo'),
        ('cancelar', 'Cancelar registros no Financeiro Novo'),
        ('administrar', 'Administrar configuracoes do Financeiro Novo')
) AS dados(acao, descricao)
WHERE NOT EXISTS (
    SELECT 1
    FROM permissoes p
    WHERE p.modulo = 'financeiro_novo'
      AND p.acao = dados.acao
);

CREATE TABLE IF NOT EXISTS financeiro3_configuracao (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    nome_modulo VARCHAR(100) NOT NULL DEFAULT 'Financeiro Novo',
    ambiente VARCHAR(20) NOT NULL DEFAULT 'HOMOLOGACAO'
        CHECK (ambiente IN ('HOMOLOGACAO', 'PILOTO', 'PRODUCAO')),
    versao_schema INTEGER NOT NULL DEFAULT 1 CHECK (versao_schema > 0),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL
);

INSERT INTO financeiro3_configuracao (id)
VALUES (1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS financeiro3_auditoria (
    id BIGSERIAL PRIMARY KEY,
    entidade VARCHAR(60) NOT NULL,
    entidade_id BIGINT,
    evento VARCHAR(60) NOT NULL,
    dados_anteriores JSONB,
    dados_novos JSONB,
    justificativa TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    username VARCHAR(120),
    ip VARCHAR(64),
    user_agent TEXT,
    request_id UUID,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_auditoria_entidade
    ON financeiro3_auditoria (entidade, entidade_id, criado_em DESC);

CREATE INDEX IF NOT EXISTS ix_financeiro3_auditoria_usuario
    ON financeiro3_auditoria (usuario_id, criado_em DESC);

CREATE OR REPLACE FUNCTION financeiro3_impedir_alteracao_auditoria()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'A auditoria do Financeiro Novo é imutável';
END;
$$;

DROP TRIGGER IF EXISTS tg_financeiro3_auditoria_imutavel
    ON financeiro3_auditoria;

CREATE TRIGGER tg_financeiro3_auditoria_imutavel
BEFORE UPDATE OR DELETE ON financeiro3_auditoria
FOR EACH ROW
EXECUTE FUNCTION financeiro3_impedir_alteracao_auditoria();

CREATE TABLE IF NOT EXISTS financeiro3_arquivos (
    id UUID PRIMARY KEY,
    storage_backend VARCHAR(20) NOT NULL
        CHECK (storage_backend IN ('VOLUME', 'BUCKET')),
    object_key VARCHAR(500) NOT NULL UNIQUE,
    nome_original VARCHAR(255) NOT NULL,
    mime_original VARCHAR(120),
    mime_canonico VARCHAR(40) NOT NULL DEFAULT 'application/pdf'
        CHECK (mime_canonico = 'application/pdf'),
    sha256_original CHAR(64) NOT NULL,
    sha256_canonico CHAR(64) NOT NULL,
    tamanho_original BIGINT NOT NULL CHECK (tamanho_original > 0),
    tamanho_canonico BIGINT NOT NULL CHECK (tamanho_canonico > 0),
    paginas INTEGER NOT NULL CHECK (paginas > 0),
    compressao_aplicada BOOLEAN NOT NULL DEFAULT TRUE,
    assinatura_digital_detectada BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'ATIVO'
        CHECK (status IN ('ATIVO', 'QUARENTENA', 'REMOVIDO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_arquivos_sha256
    ON financeiro3_arquivos (sha256_canonico);

CREATE TABLE IF NOT EXISTS financeiro3_anexos (
    id BIGSERIAL PRIMARY KEY,
    arquivo_id UUID NOT NULL REFERENCES financeiro3_arquivos(id) ON DELETE RESTRICT,
    entidade VARCHAR(60) NOT NULL,
    entidade_id BIGINT NOT NULL,
    categoria VARCHAR(40) NOT NULL DEFAULT 'DOCUMENTO',
    descricao VARCHAR(255),
    status VARCHAR(20) NOT NULL DEFAULT 'ATIVO'
        CHECK (status IN ('ATIVO', 'REMOVIDO')),
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removido_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    removido_em TIMESTAMPTZ,
    motivo_remocao TEXT,
    UNIQUE (arquivo_id, entidade, entidade_id, categoria)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_anexos_entidade
    ON financeiro3_anexos (entidade, entidade_id, status);

COMMIT;
