BEGIN;

INSERT INTO permissoes(modulo,acao,descricao)
VALUES
    ('auth','administrar','Administrar usuários, perfis, permissões e auditoria; concede acesso total ao sistema'),
    ('operacao','visualizar','Acessar as páginas de produção, registros, resumos e cadastros da Operação'),
    ('operacao','criar','Criar planos, registros, observações e cadastros da Operação'),
    ('operacao','editar','Editar planos, registros e cadastros da Operação'),
    ('operacao','excluir','Excluir registros e cadastros da Operação'),
    ('equipamentos','visualizar','Acessar as páginas, controles e partes diárias de Equipamentos'),
    ('equipamentos','criar','Criar máquinas, atividades, pontos e partes diárias'),
    ('equipamentos','editar','Editar máquinas, atividades, pontos e partes diárias'),
    ('equipamentos','excluir','Excluir máquinas, atividades, pontos e partes diárias'),
    ('equipamentos','exportar','Exportar dados e relatórios de Equipamentos'),
    ('colaboradores','visualizar','Acessar todas as páginas e dados de Colaboradores'),
    ('colaboradores','criar','Criar e alterar registros e cadastros de Colaboradores'),
    ('financeiro','visualizar','Acessar todas as páginas do Financeiro'),
    ('financeiro','criar','Criar OM, RD, despesas, faturas e demais registros financeiros'),
    ('financeiro','editar','Editar registros do Financeiro'),
    ('financeiro','aprovar','Aprovar registros e etapas do Financeiro'),
    ('financeiro','gerar_nd','Gerar notas de débito no Financeiro'),
    ('financeiro_novo','visualizar','Acessar despesas, missões, reembolsos, previsões e relatórios do Financeiro Novo'),
    ('financeiro_novo','criar','Criar registros no Financeiro Novo'),
    ('financeiro_novo','editar','Editar registros no Financeiro Novo'),
    ('financeiro_novo','aprovar','Aprovar registros no Financeiro Novo'),
    ('financeiro_novo','pagar','Registrar pagamentos no Financeiro Novo'),
    ('financeiro_novo','cancelar','Cancelar registros no Financeiro Novo'),
    ('financeiro_novo','administrar','Administrar configurações e cadastros do Financeiro Novo'),
    ('perfil_pagamentos','visualizar','Acessar perfis, painel e contas do Perfil de Pagamentos'),
    ('perfil_pagamentos','administrar','Criar, editar e desativar perfis de pagamentos'),
    ('perfil_pagamentos','editar','Editar e vincular contas controladas'),
    ('perfil_pagamentos','pagar','Marcar ou reabrir pagamentos'),
    ('perfil_pagamentos','reembolsar','Marcar ou reverter reembolsos'),
    ('perfil_pagamentos','sincronizar','Executar a sincronização manual das contas'),
    ('bot','visualizar','Acessar as páginas do Bot Prumat'),
    ('bot','administrar','Configurar colaboradores, perfis e fluxos do Bot Prumat'),
    ('bot','operar','Acompanhar e executar solicitações do Bot Prumat'),
    ('bot','auditar','Consultar a auditoria do Bot Prumat'),
    ('fornecedores','visualizar','Acessar fornecedores, solicitações, orçamentos e arquivos'),
    ('fornecedores','administrar','Cadastrar fornecedores, criar e cancelar solicitações'),
    ('fornecedores','aprovar','Negociar, revisar, rejeitar e aprovar orçamentos'),
    ('fornecedores','fechar','Acompanhar a execução e fechar serviços de fornecedores')
ON CONFLICT (modulo,acao)
DO UPDATE SET descricao=EXCLUDED.descricao;

COMMIT;
