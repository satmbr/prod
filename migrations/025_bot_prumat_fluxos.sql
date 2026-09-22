BEGIN;

INSERT INTO permissoes (modulo, acao, descricao)
VALUES
    ('bot', 'visualizar', 'Visualizar o módulo Bot Prumat'),
    ('bot', 'administrar', 'Configurar colaboradores, perfis e fluxos do Bot Prumat'),
    ('bot', 'operar', 'Acompanhar e executar solicitações do Bot Prumat'),
    ('bot', 'auditar', 'Consultar a auditoria do Bot Prumat')
ON CONFLICT (modulo, acao) DO UPDATE SET descricao = EXCLUDED.descricao;

CREATE TABLE IF NOT EXISTS bot_perfis (
    id BIGSERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL UNIQUE,
    descricao TEXT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_colaboradores (
    id BIGSERIAL PRIMARY KEY,
    colaborador_id INTEGER NOT NULL UNIQUE REFERENCES colaborador_prumat(id) ON DELETE RESTRICT,
    usuario_id INTEGER UNIQUE REFERENCES usuarios(id) ON DELETE SET NULL,
    telegram_user_id BIGINT UNIQUE,
    telegram_chat_id BIGINT UNIQUE,
    telegram_username VARCHAR(200),
    telegram_nome VARCHAR(240),
    vinculo_token VARCHAR(64) NOT NULL UNIQUE DEFAULT replace(gen_random_uuid()::text, '-', ''),
    vinculado_em TIMESTAMPTZ,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_colaborador_perfis (
    colaborador_id BIGINT NOT NULL REFERENCES bot_colaboradores(id) ON DELETE CASCADE,
    perfil_id BIGINT NOT NULL REFERENCES bot_perfis(id) ON DELETE CASCADE,
    PRIMARY KEY (colaborador_id, perfil_id)
);

CREATE TABLE IF NOT EXISTS bot_fluxos (
    id BIGSERIAL PRIMARY KEY,
    codigo VARCHAR(40) NOT NULL UNIQUE,
    nome VARCHAR(140) NOT NULL,
    categoria VARCHAR(60) NOT NULL,
    descricao TEXT,
    modelo VARCHAR(30) NOT NULL DEFAULT 'PERSONALIZADO',
    campos JSONB NOT NULL DEFAULT '[]'::jsonb,
    estrategia_aprovacao VARCHAR(20) NOT NULL DEFAULT 'QUALQUER_UM'
        CHECK (estrategia_aprovacao IN ('QUALQUER_UM', 'TODOS', 'QUORUM')),
    quorum INTEGER NOT NULL DEFAULT 1 CHECK (quorum > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'RASCUNHO'
        CHECK (status IN ('RASCUNHO', 'TESTE', 'PUBLICADO', 'PAUSADO', 'ARQUIVADO')),
    versao INTEGER NOT NULL DEFAULT 1,
    permite_alterar BOOLEAN NOT NULL DEFAULT TRUE,
    permite_cancelar BOOLEAN NOT NULL DEFAULT TRUE,
    criado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_fluxo_solicitantes (
    fluxo_id BIGINT NOT NULL REFERENCES bot_fluxos(id) ON DELETE CASCADE,
    perfil_id BIGINT NOT NULL REFERENCES bot_perfis(id) ON DELETE CASCADE,
    PRIMARY KEY (fluxo_id, perfil_id)
);

CREATE TABLE IF NOT EXISTS bot_fluxo_aprovadores (
    fluxo_id BIGINT NOT NULL REFERENCES bot_fluxos(id) ON DELETE CASCADE,
    colaborador_id BIGINT NOT NULL REFERENCES bot_colaboradores(id) ON DELETE CASCADE,
    ordem INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (fluxo_id, colaborador_id)
);

CREATE TABLE IF NOT EXISTS bot_fluxo_executores (
    fluxo_id BIGINT NOT NULL REFERENCES bot_fluxos(id) ON DELETE CASCADE,
    colaborador_id BIGINT NOT NULL REFERENCES bot_colaboradores(id) ON DELETE CASCADE,
    PRIMARY KEY (fluxo_id, colaborador_id)
);

CREATE SEQUENCE IF NOT EXISTS bot_solicitacao_numero_seq START WITH 1;

CREATE TABLE IF NOT EXISTS bot_solicitacoes (
    id BIGSERIAL PRIMARY KEY,
    numero VARCHAR(24) NOT NULL UNIQUE DEFAULT (
        'BP-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
        lpad(nextval('bot_solicitacao_numero_seq')::text, 6, '0')
    ),
    fluxo_id BIGINT NOT NULL REFERENCES bot_fluxos(id) ON DELETE RESTRICT,
    fluxo_versao INTEGER NOT NULL,
    solicitante_id BIGINT NOT NULL REFERENCES bot_colaboradores(id) ON DELETE RESTRICT,
    beneficiario_id BIGINT REFERENCES bot_colaboradores(id) ON DELETE RESTRICT,
    dados JSONB NOT NULL DEFAULT '{}'::jsonb,
    resumo TEXT,
    status VARCHAR(28) NOT NULL DEFAULT 'RASCUNHO'
        CHECK (status IN ('RASCUNHO', 'AGUARDANDO_APROVACAO', 'APROVADA', 'REJEITADA', 'EM_EXECUCAO', 'CONCLUIDA', 'CANCELADA')),
    decisao_por BIGINT REFERENCES bot_colaboradores(id) ON DELETE SET NULL,
    decisao_em TIMESTAMPTZ,
    motivo_decisao TEXT,
    executor_id BIGINT REFERENCES bot_colaboradores(id) ON DELETE SET NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_solicitacao_aprovacoes (
    solicitacao_id BIGINT NOT NULL REFERENCES bot_solicitacoes(id) ON DELETE CASCADE,
    aprovador_id BIGINT NOT NULL REFERENCES bot_colaboradores(id) ON DELETE RESTRICT,
    status VARCHAR(14) NOT NULL DEFAULT 'PENDENTE'
        CHECK (status IN ('PENDENTE', 'APROVADA', 'REJEITADA', 'ENCERRADA')),
    decisao_em TIMESTAMPTZ,
    observacao TEXT,
    PRIMARY KEY (solicitacao_id, aprovador_id)
);

CREATE TABLE IF NOT EXISTS bot_solicitacao_eventos (
    id BIGSERIAL PRIMARY KEY,
    solicitacao_id BIGINT NOT NULL REFERENCES bot_solicitacoes(id) ON DELETE CASCADE,
    tipo VARCHAR(40) NOT NULL,
    descricao TEXT NOT NULL,
    colaborador_id BIGINT REFERENCES bot_colaboradores(id) ON DELETE SET NULL,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    telegram_user_id BIGINT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_conversas (
    chat_id BIGINT PRIMARY KEY,
    colaborador_id BIGINT NOT NULL REFERENCES bot_colaboradores(id) ON DELETE CASCADE,
    estado VARCHAR(40) NOT NULL,
    fluxo_id BIGINT REFERENCES bot_fluxos(id) ON DELETE CASCADE,
    solicitacao_id BIGINT REFERENCES bot_solicitacoes(id) ON DELETE CASCADE,
    indice_campo INTEGER NOT NULL DEFAULT 0,
    dados JSONB NOT NULL DEFAULT '{}'::jsonb,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE bot_conversas
    ADD COLUMN IF NOT EXISTS solicitacao_id BIGINT REFERENCES bot_solicitacoes(id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS bot_telegram_updates (
    update_id BIGINT PRIMARY KEY,
    chat_id BIGINT,
    status VARCHAR(12) NOT NULL DEFAULT 'INICIADO'
        CHECK (status IN ('INICIADO', 'CONCLUIDO', 'ERRO')),
    mensagem TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_bot_solicitacoes_status ON bot_solicitacoes(status, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_bot_eventos_solicitacao ON bot_solicitacao_eventos(solicitacao_id, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_bot_aprovacoes_pendentes ON bot_solicitacao_aprovacoes(aprovador_id, status);

INSERT INTO bot_perfis (nome, descricao)
VALUES
    ('Conservador', 'Colaborador de campo que recebe serviços e solicitações.'),
    ('Encarregado', 'Responsável por iniciar solicitações da equipe.'),
    ('Gerente', 'Responsável por aprovar ou rejeitar solicitações.'),
    ('Comprador', 'Responsável por executar compras e reservas.')
ON CONFLICT (nome) DO NOTHING;

INSERT INTO bot_fluxos (codigo, nome, categoria, descricao, modelo, campos)
VALUES
    ('PASSAGEM', 'Compra de passagens', 'Viagens', 'Solicitação de passagem para um colaborador.', 'PASSAGEM',
     '[{"chave":"beneficiario","rotulo":"Matrícula ou nome do passageiro","tipo":"texto","obrigatorio":true},{"chave":"origem","rotulo":"Cidade de origem","tipo":"texto","obrigatorio":true},{"chave":"destino","rotulo":"Cidade de destino","tipo":"texto","obrigatorio":true},{"chave":"ida","rotulo":"Data da ida (DD/MM/AAAA)","tipo":"data","obrigatorio":true},{"chave":"volta","rotulo":"Data da volta ou SEM VOLTA","tipo":"texto","obrigatorio":true},{"chave":"observacao","rotulo":"Observações ou NENHUMA","tipo":"texto","obrigatorio":false}]'::jsonb),
    ('MATERIAL', 'Compra de material', 'Compras', 'Solicitação de aquisição de materiais.', 'MATERIAL',
     '[{"chave":"item","rotulo":"Material solicitado","tipo":"texto","obrigatorio":true},{"chave":"quantidade","rotulo":"Quantidade","tipo":"texto","obrigatorio":true},{"chave":"local","rotulo":"Local de entrega","tipo":"texto","obrigatorio":true},{"chave":"justificativa","rotulo":"Justificativa","tipo":"texto","obrigatorio":true}]'::jsonb),
    ('EPI', 'Solicitação de EPI', 'Suprimentos', 'Solicitação de equipamento de proteção individual.', 'EPI',
     '[{"chave":"beneficiario","rotulo":"Matrícula ou nome do colaborador","tipo":"texto","obrigatorio":true},{"chave":"epi","rotulo":"EPI solicitado","tipo":"texto","obrigatorio":true},{"chave":"tamanho","rotulo":"Tamanho ou NÃO SE APLICA","tipo":"texto","obrigatorio":true},{"chave":"quantidade","rotulo":"Quantidade","tipo":"texto","obrigatorio":true}]'::jsonb),
    ('REEMBOLSO', 'Solicitação de reembolso', 'Financeiro', 'Solicitação de análise e pagamento de reembolso.', 'REEMBOLSO',
     '[{"chave":"descricao","rotulo":"Descrição da despesa","tipo":"texto","obrigatorio":true},{"chave":"data","rotulo":"Data da despesa (DD/MM/AAAA)","tipo":"data","obrigatorio":true},{"chave":"valor","rotulo":"Valor (ex.: 125,50)","tipo":"valor","obrigatorio":true},{"chave":"justificativa","rotulo":"Justificativa","tipo":"texto","obrigatorio":true}]'::jsonb)
ON CONFLICT (codigo) DO NOTHING;

COMMIT;
