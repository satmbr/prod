BEGIN;

ALTER TABLE financeiro3_pagamento_perfis
    ADD COLUMN IF NOT EXISTS portal_token VARCHAR(100),
    ADD COLUMN IF NOT EXISTS storage_prefix VARCHAR(180);

UPDATE financeiro3_pagamento_perfis
SET portal_token = md5(random()::text || clock_timestamp()::text || id::text)
                 || md5(random()::text || clock_timestamp()::text || nome),
    storage_prefix = 'perfil_pagamentos/' || id,
    pasta_raiz_id = 'bucket-profile-' || id,
    pasta_raiz_link = '',
    pasta_novas_id = 'novas_contas',
    pasta_controladas_id = 'contas_controladas',
    pasta_quitadas_id = 'contas_quitadas',
    pasta_comprovantes_id = 'comprovantes',
    pasta_erros_id = 'contas_com_erro',
    status_conexao = 'PENDENTE',
    ultimo_erro = NULL,
    atualizado_em = NOW()
WHERE portal_token IS NULL OR storage_prefix IS NULL;

ALTER TABLE financeiro3_pagamento_perfis
    ALTER COLUMN portal_token SET NOT NULL,
    ALTER COLUMN storage_prefix SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_portal_token
    ON financeiro3_pagamento_perfis (portal_token);
CREATE UNIQUE INDEX IF NOT EXISTS ux_financeiro3_pagamento_perfil_storage_prefix
    ON financeiro3_pagamento_perfis (storage_prefix);

UPDATE permissoes
SET descricao='Executar manualmente a sincronização com o portal de arquivos'
WHERE modulo='perfil_pagamentos' AND acao='sincronizar';

UPDATE financeiro3_pagamento_importacao_erros
SET resolvido=TRUE,resolvido_em=NOW(),ultima_ocorrencia_em=NOW()
WHERE NOT resolvido AND drive_file_id !~ '^[0-9a-f]{32}$';

UPDATE financeiro3_pagamento_contas
SET status_sincronizacao='ERRO',pasta_atual='PENDENTE_MOVIMENTACAO',
    ultimo_erro='Arquivo anterior era do Google Drive. Reenvie-o pelo portal se precisar mantê-lo disponível.',
    atualizado_em=NOW()
WHERE drive_file_id !~ '^[0-9a-f]{32}$';

COMMIT;
