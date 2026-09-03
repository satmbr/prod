BEGIN;

INSERT INTO permissoes (modulo, acao, descricao)
SELECT 'perfil_pagamentos', dados.acao, dados.descricao
FROM (
    VALUES
        ('visualizar', 'Visualizar todos os perfis e contas do Perfil de Pagamentos'),
        ('administrar', 'Criar, editar e desativar perfis de pagamentos'),
        ('editar', 'Editar dados das contas controladas'),
        ('pagar', 'Marcar ou reabrir pagamentos das contas controladas'),
        ('reembolsar', 'Marcar ou reverter reembolsos das contas controladas'),
        ('sincronizar', 'Executar manualmente a sincronização com o Google Drive')
) AS dados(acao, descricao)
WHERE NOT EXISTS (
    SELECT 1 FROM permissoes p
    WHERE p.modulo='perfil_pagamentos' AND p.acao=dados.acao
);

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_perfis (
    id BIGSERIAL PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    matricula VARCHAR(40) NOT NULL,
    gmail VARCHAR(254) NOT NULL,
    pasta_raiz_id VARCHAR(180) NOT NULL,
    pasta_raiz_link TEXT NOT NULL,
    pasta_novas_id VARCHAR(180),
    pasta_controladas_id VARCHAR(180),
    pasta_quitadas_id VARCHAR(180),
    pasta_comprovantes_id VARCHAR(180),
    pasta_erros_id VARCHAR(180),
    status_conexao VARCHAR(16) NOT NULL DEFAULT 'PENDENTE'
        CHECK (status_conexao IN ('PENDENTE','ATIVA','ERRO')),
    ultimo_erro TEXT,
    ultima_sincronizacao_em TIMESTAMPTZ,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_matricula
    ON financeiro3_pagamento_perfis (LOWER(matricula));
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_gmail
    ON financeiro3_pagamento_perfis (LOWER(gmail));
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_pasta
    ON financeiro3_pagamento_perfis (pasta_raiz_id);

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_contas (
    id BIGSERIAL PRIMARY KEY,
    numero VARCHAR(20) UNIQUE,
    perfil_id BIGINT NOT NULL REFERENCES financeiro3_pagamento_perfis(id) ON DELETE RESTRICT,
    drive_file_id VARCHAR(180) NOT NULL UNIQUE,
    drive_nome_original VARCHAR(500) NOT NULL,
    drive_nome_atual VARCHAR(500) NOT NULL,
    drive_web_view_link TEXT,
    mime_type VARCHAR(160),
    valor NUMERIC(18,2) NOT NULL CHECK (valor > 0),
    data_documento DATE NOT NULL,
    data_vencimento DATE NOT NULL,
    descricao VARCHAR(220) NOT NULL,
    status_pagamento VARCHAR(10) NOT NULL DEFAULT 'ABERTA'
        CHECK (status_pagamento IN ('ABERTA','PAGA')),
    status_reembolso VARCHAR(14) NOT NULL DEFAULT 'PENDENTE'
        CHECK (status_reembolso IN ('PENDENTE','REEMBOLSADA')),
    numero_om VARCHAR(80),
    data_pagamento DATE,
    data_reembolso DATE,
    pagamento_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    reembolso_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    pasta_atual VARCHAR(24) NOT NULL DEFAULT 'CONTROLADAS'
        CHECK (pasta_atual IN ('CONTROLADAS','QUITADAS','ERRO','PENDENTE_MOVIMENTACAO')),
    status_sincronizacao VARCHAR(24) NOT NULL DEFAULT 'PENDENTE'
        CHECK (status_sincronizacao IN ('PENDENTE','OK','AGUARDANDO_OM','ERRO')),
    ultimo_erro TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (data_vencimento >= data_documento),
    CHECK (status_pagamento='PAGA' OR data_pagamento IS NULL),
    CHECK (status_reembolso='REEMBOLSADA' OR (data_reembolso IS NULL AND numero_om IS NULL))
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_contas_perfil_vencimento
    ON financeiro3_pagamento_contas (perfil_id,data_vencimento,id);
CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_contas_status
    ON financeiro3_pagamento_contas (status_pagamento,status_reembolso,data_vencimento);

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_comprovantes (
    id BIGSERIAL PRIMARY KEY,
    conta_id BIGINT NOT NULL REFERENCES financeiro3_pagamento_contas(id) ON DELETE RESTRICT,
    drive_file_id VARCHAR(180) NOT NULL UNIQUE,
    nome_arquivo VARCHAR(500) NOT NULL,
    mime_type VARCHAR(160),
    drive_web_view_link TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    localizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_comprovantes_conta
    ON financeiro3_pagamento_comprovantes (conta_id,ativo,id);

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_importacao_erros (
    id BIGSERIAL PRIMARY KEY,
    perfil_id BIGINT NOT NULL REFERENCES financeiro3_pagamento_perfis(id) ON DELETE RESTRICT,
    drive_file_id VARCHAR(180) NOT NULL,
    tipo VARCHAR(16) NOT NULL CHECK (tipo IN ('CONTA','COMPROVANTE')),
    nome_arquivo VARCHAR(500) NOT NULL,
    drive_web_view_link TEXT,
    mensagem TEXT NOT NULL,
    resolvido BOOLEAN NOT NULL DEFAULT FALSE,
    primeira_ocorrencia_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultima_ocorrencia_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolvido_em TIMESTAMPTZ,
    UNIQUE (perfil_id,drive_file_id,tipo)
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_erros_abertos
    ON financeiro3_pagamento_importacao_erros (perfil_id,resolvido,ultima_ocorrencia_em DESC);

CREATE TABLE IF NOT EXISTS financeiro3_pagamento_sincronizacoes (
    id BIGSERIAL PRIMARY KEY,
    perfil_id BIGINT REFERENCES financeiro3_pagamento_perfis(id) ON DELETE SET NULL,
    origem VARCHAR(10) NOT NULL CHECK (origem IN ('AUTOMATICA','MANUAL')),
    status VARCHAR(12) NOT NULL DEFAULT 'INICIADA'
        CHECK (status IN ('INICIADA','SUCESSO','PARCIAL','ERRO')),
    contas_novas INTEGER NOT NULL DEFAULT 0 CHECK (contas_novas >= 0),
    comprovantes_novos INTEGER NOT NULL DEFAULT 0 CHECK (comprovantes_novos >= 0),
    arquivos_movidos INTEGER NOT NULL DEFAULT 0 CHECK (arquivos_movidos >= 0),
    erros INTEGER NOT NULL DEFAULT 0 CHECK (erros >= 0),
    mensagem TEXT,
    executado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    iniciado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    concluido_em TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_financeiro3_pagamento_sync_perfil
    ON financeiro3_pagamento_sincronizacoes (perfil_id,iniciado_em DESC);

UPDATE financeiro3_configuracao
SET versao_schema=12, atualizado_em=NOW()
WHERE id=1 AND versao_schema<12;

COMMIT;
