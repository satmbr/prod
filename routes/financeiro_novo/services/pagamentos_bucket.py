import os
import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from db import get_engine
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.pagamentos_drive import (
    EXTENSOES_ACEITAS,
    TIPOS_ACEITOS,
    NomeContaInvalido,
    conta_pronta_para_quitadas,
    interpretar_nome_conta,
    nome_controlado,
    numero_conta_do_comprovante,
)


PASTAS = (
    "novas_contas",
    "contas_controladas",
    "contas_quitadas",
    "comprovantes",
    "contas_com_erro",
)
PASTAS_GRAVAVEIS = {"novas_contas", "comprovantes"}
PASTAS_EDITAVEIS = PASTAS_GRAVAVEIS | {"contas_com_erro"}


class PagamentosStorageErro(RuntimeError):
    pass


def _env(*nomes):
    for nome in nomes:
        valor = (os.getenv(nome) or "").strip()
        if valor:
            return valor
    return None


def configuracao_bucket() -> dict:
    dados = {
        "bucket": _env("BUCKET", "AWS_S3_BUCKET_NAME", "BUCKET_NAME"),
        "endpoint": _env("ENDPOINT", "AWS_ENDPOINT_URL", "BUCKET_ENDPOINT"),
        "access_key": _env("ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID", "BUCKET_ACCESS_KEY_ID"),
        "secret_key": _env("SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY", "BUCKET_SECRET_ACCESS_KEY"),
        "region": _env("REGION", "AWS_DEFAULT_REGION", "BUCKET_REGION") or "auto",
        "url_style": (_env("AWS_S3_URL_STYLE", "BUCKET_URL_STYLE") or "virtual").lower(),
    }
    ausentes = [campo for campo in ("bucket", "endpoint", "access_key", "secret_key") if not dados[campo]]
    if ausentes:
        raise PagamentosStorageErro(
            "Conecte um Railway Bucket e injete BUCKET, ENDPOINT, ACCESS_KEY_ID e SECRET_ACCESS_KEY."
        )
    return dados


def bucket_configurado() -> bool:
    try:
        configuracao_bucket()
        return True
    except PagamentosStorageErro:
        return False


def _s3():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise PagamentosStorageErro("A biblioteca de armazenamento S3 não está instalada.") from exc
    cfg = configuracao_bucket()
    estilo = "path" if cfg["url_style"] == "path" else "virtual"
    cliente = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint"],
        aws_access_key_id=cfg["access_key"],
        aws_secret_access_key=cfg["secret_key"],
        region_name=cfg["region"],
        config=Config(signature_version="s3v4", s3={"addressing_style": estilo}),
    )
    return cliente, cfg["bucket"]


def _prefixo(perfil: dict | int) -> str:
    if isinstance(perfil, int):
        return f"perfil_pagamentos/{perfil}"
    return (perfil.get("storage_prefix") or f"perfil_pagamentos/{perfil['id']}").strip("/")


def _validar_pasta(pasta: str) -> str:
    if pasta not in PASTAS:
        raise PagamentosStorageErro("Pasta inválida.")
    return pasta


def limpar_nome_arquivo(nome: str) -> str:
    nome = Path((nome or "").replace("\\", "/")).name
    nome = re.sub(r"[\x00-\x1f\x7f]", "", nome).strip().strip(".")
    nome = re.sub(r"\s+", " ", nome)
    if not nome or len(nome) > 500:
        raise PagamentosStorageErro("O nome do arquivo deve ter entre 1 e 500 caracteres.")
    return nome


def _chave(perfil: dict | int, pasta: str, arquivo_id: str, nome: str) -> str:
    return f"{_prefixo(perfil)}/{_validar_pasta(pasta)}/{arquivo_id}/{limpar_nome_arquivo(nome)}"


def listar_arquivos(perfil: dict | int, pasta: str) -> list[dict]:
    pasta = _validar_pasta(pasta)
    s3, bucket = _s3()
    prefixo = f"{_prefixo(perfil)}/{pasta}/"
    token = None
    arquivos = []
    while True:
        params = {"Bucket": bucket, "Prefix": prefixo, "MaxKeys": 1000}
        if token:
            params["ContinuationToken"] = token
        resposta = s3.list_objects_v2(**params)
        for item in resposta.get("Contents", []):
            relativo = item["Key"][len(prefixo):]
            partes = relativo.split("/", 1)
            if len(partes) != 2 or not re.fullmatch(r"[0-9a-f]{32}", partes[0]):
                continue
            arquivos.append({
                "id": partes[0], "name": partes[1], "key": item["Key"],
                "size": item.get("Size", 0), "modified": item.get("LastModified"),
                "mimeType": None, "webViewLink": None,
            })
        token = resposta.get("NextContinuationToken")
        if not token:
            break
    return sorted(arquivos, key=lambda item: item["name"].lower())


def localizar_arquivo(perfil: dict | int, arquivo_id: str, pastas=None) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{32}", arquivo_id or ""):
        return None
    for pasta in pastas or PASTAS:
        for arquivo in listar_arquivos(perfil, pasta):
            if arquivo["id"] == arquivo_id:
                return {**arquivo, "pasta": pasta}
    return None


def enviar_arquivo(perfil: dict | int, pasta: str, arquivo) -> dict:
    if pasta not in PASTAS_GRAVAVEIS:
        raise PagamentosStorageErro("Envios são permitidos somente em novas_contas e comprovantes.")
    nome = limpar_nome_arquivo(arquivo.filename)
    extensao = Path(nome).suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise PagamentosStorageErro("Use arquivos PDF, JPG, JPEG ou PNG.")
    arquivo_id = uuid.uuid4().hex
    chave = _chave(perfil, pasta, arquivo_id, nome)
    s3, bucket = _s3()
    s3.put_object(
        Bucket=bucket, Key=chave, Body=arquivo.stream,
        ContentType=arquivo.mimetype if arquivo.mimetype in TIPOS_ACEITOS else "application/octet-stream",
    )
    return {"id": arquivo_id, "name": nome, "key": chave, "pasta": pasta}


def _mover(perfil: dict | int, arquivo: dict, destino: str, novo_nome: str | None = None) -> dict:
    destino = _validar_pasta(destino)
    nome = limpar_nome_arquivo(novo_nome or arquivo["name"])
    nova_chave = _chave(perfil, destino, arquivo["id"], nome)
    if nova_chave == arquivo["key"]:
        return {**arquivo, "name": nome, "pasta": destino}
    s3, bucket = _s3()
    s3.copy_object(Bucket=bucket, Key=nova_chave, CopySource={"Bucket": bucket, "Key": arquivo["key"]})
    s3.delete_object(Bucket=bucket, Key=arquivo["key"])
    return {**arquivo, "name": nome, "key": nova_chave, "pasta": destino}


def renomear_arquivo(perfil: dict | int, pasta: str, arquivo_id: str, novo_nome: str) -> dict:
    if pasta not in PASTAS_EDITAVEIS:
        raise PagamentosStorageErro("Esta pasta é protegida contra alterações manuais.")
    arquivo = localizar_arquivo(perfil, arquivo_id, [pasta])
    if not arquivo:
        raise PagamentosStorageErro("Arquivo não encontrado.")
    return _mover(perfil, arquivo, pasta, novo_nome)


def excluir_arquivo(perfil: dict | int, pasta: str, arquivo_id: str) -> None:
    if pasta not in PASTAS_EDITAVEIS:
        raise PagamentosStorageErro("Esta pasta é protegida contra exclusões manuais.")
    arquivo = localizar_arquivo(perfil, arquivo_id, [pasta])
    if not arquivo:
        raise PagamentosStorageErro("Arquivo não encontrado.")
    s3, bucket = _s3()
    s3.delete_object(Bucket=bucket, Key=arquivo["key"])


def reenviar_arquivo_erro(perfil: dict, arquivo_id: str, novo_nome: str) -> dict:
    arquivo = localizar_arquivo(perfil, arquivo_id, ["contas_com_erro"])
    if not arquivo:
        raise PagamentosStorageErro("Arquivo não encontrado em contas_com_erro.")
    with get_engine().connect() as conn:
        tipo = conn.execute(text("""
            SELECT tipo FROM financeiro3_pagamento_importacao_erros
            WHERE perfil_id=:perfil AND drive_file_id=:arquivo AND NOT resolvido
            ORDER BY id DESC LIMIT 1
        """), {"perfil": perfil["id"], "arquivo": arquivo_id}).scalar()
    destino = "comprovantes" if tipo == "COMPROVANTE" else "novas_contas"
    return _mover(perfil, arquivo, destino, novo_nome)


def url_temporaria(perfil: dict | int, arquivo_id: str, *, download=False) -> str:
    arquivo = localizar_arquivo(perfil, arquivo_id)
    if not arquivo:
        raise PagamentosStorageErro("Arquivo não encontrado.")
    s3, bucket = _s3()
    modo = "attachment" if download else "inline"
    disposicao = f"{modo}; filename*=UTF-8''{quote(arquivo['name'])}"
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": arquivo["key"], "ResponseContentDisposition": disposicao},
        ExpiresIn=300,
    )


def _registrar_erro(conn, perfil_id: int, arquivo: dict, tipo: str, mensagem: str):
    conn.execute(text("""
        INSERT INTO financeiro3_pagamento_importacao_erros
          (perfil_id,drive_file_id,tipo,nome_arquivo,drive_web_view_link,mensagem)
        VALUES (:perfil,:arquivo,:tipo,:nome,NULL,:mensagem)
        ON CONFLICT (perfil_id,drive_file_id,tipo) DO UPDATE SET
          nome_arquivo=EXCLUDED.nome_arquivo,mensagem=EXCLUDED.mensagem,
          resolvido=FALSE,resolvido_em=NULL,ultima_ocorrencia_em=NOW()
    """), {"perfil": perfil_id, "arquivo": arquivo["id"], "tipo": tipo,
             "nome": arquivo.get("name") or "", "mensagem": mensagem})


def _resolver_erro(conn, perfil_id: int, arquivo_id: str, tipo: str):
    conn.execute(text("""
        UPDATE financeiro3_pagamento_importacao_erros
        SET resolvido=TRUE,resolvido_em=NOW(),ultima_ocorrencia_em=NOW()
        WHERE perfil_id=:perfil AND drive_file_id=:arquivo AND tipo=:tipo AND NOT resolvido
    """), {"perfil": perfil_id, "arquivo": arquivo_id, "tipo": tipo})


def _criar_ou_obter_conta(perfil: dict, arquivo: dict, dados) -> tuple[dict, bool]:
    with get_engine().begin() as conn:
        existente = conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_contas WHERE drive_file_id=:arquivo FOR UPDATE
        """), {"arquivo": arquivo["id"]}).mappings().first()
        if existente:
            _resolver_erro(conn, perfil["id"], arquivo["id"], "CONTA")
            return dict(existente), False
        conta = conn.execute(text("""
            INSERT INTO financeiro3_pagamento_contas
              (perfil_id,drive_file_id,drive_nome_original,drive_nome_atual,drive_web_view_link,
               mime_type,valor,data_documento,data_vencimento,descricao,status_pagamento,
               status_reembolso,data_pagamento,data_reembolso,status_sincronizacao)
            VALUES (:perfil,:arquivo,:nome,:nome,NULL,:mime,:valor,:documento,:vencimento,
                    :descricao,:pagamento,:reembolso,:data_pagamento,:data_reembolso,:sync)
            RETURNING *
        """), {
            "perfil": perfil["id"], "arquivo": arquivo["id"], "nome": arquivo["name"],
            "mime": Path(arquivo["name"]).suffix.lower(), "valor": dados.valor,
            "documento": dados.data_documento, "vencimento": dados.data_vencimento,
            "descricao": dados.descricao, "pagamento": dados.status_pagamento,
            "reembolso": dados.status_reembolso,
            "data_pagamento": date.today() if dados.status_pagamento == "PAGA" else None,
            "data_reembolso": date.today() if dados.status_reembolso == "REEMBOLSADA" else None,
            "sync": "AGUARDANDO_OM" if dados.status_reembolso == "REEMBOLSADA" else "PENDENTE",
        }).mappings().one()
        numero = f"CP-{conta['id']:06d}"
        conta = conn.execute(text("""
            UPDATE financeiro3_pagamento_contas SET numero=:numero WHERE id=:id RETURNING *
        """), {"numero": numero, "id": conta["id"]}).mappings().one()
        _resolver_erro(conn, perfil["id"], arquivo["id"], "CONTA")
        registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta["id"],
                         evento="IMPORTADA_PORTAL", dados_novos=dict(conta))
        return dict(conta), True


def _atualizar_arquivo_conta(conta: dict, arquivo: dict, destino: str, status: str, erro=None):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE financeiro3_pagamento_contas SET drive_nome_atual=:nome,
              drive_web_view_link=NULL,pasta_atual=:pasta,status_sincronizacao=:status,
              ultimo_erro=:erro,atualizado_em=NOW() WHERE id=:id
        """), {"nome": arquivo.get("name", conta["drive_nome_atual"]), "pasta": destino,
                 "status": status, "erro": erro, "id": conta["id"]})


def _sincronizar_novas(perfil: dict, contadores: dict):
    for arquivo in listar_arquivos(perfil, "novas_contas"):
        try:
            dados = interpretar_nome_conta(arquivo["name"])
            conta, criada = _criar_ou_obter_conta(perfil, arquivo, dados)
            destino_status = "QUITADAS" if conta_pronta_para_quitadas(conta) else "CONTROLADAS"
            destino_pasta = "contas_quitadas" if destino_status == "QUITADAS" else "contas_controladas"
            movido = _mover(perfil, arquivo, destino_pasta, nome_controlado(conta, dados.extensao))
            status = "AGUARDANDO_OM" if conta["status_reembolso"] == "REEMBOLSADA" and not conta.get("numero_om") else "OK"
            _atualizar_arquivo_conta(conta, movido, destino_status, status)
            contadores["contas_novas"] += int(criada)
            contadores["arquivos_movidos"] += 1
        except Exception as exc:
            contadores["erros"] += 1
            with get_engine().begin() as conn:
                _registrar_erro(conn, perfil["id"], arquivo, "CONTA", str(exc))
            try:
                _mover(perfil, arquivo, "contas_com_erro")
            except Exception:
                pass


def _sincronizar_comprovantes(perfil: dict, contadores: dict):
    arquivos = listar_arquivos(perfil, "comprovantes")
    ids_encontrados = [arquivo["id"] for arquivo in arquivos]
    with get_engine().begin() as conn:
        if ids_encontrados:
            conn.execute(text("""
                UPDATE financeiro3_pagamento_comprovantes cp SET ativo=FALSE,atualizado_em=NOW()
                FROM financeiro3_pagamento_contas c
                WHERE cp.conta_id=c.id AND c.perfil_id=:perfil AND cp.ativo
                  AND NOT (cp.drive_file_id = ANY(:ids))
            """), {"perfil": perfil["id"], "ids": ids_encontrados})
        else:
            conn.execute(text("""
                UPDATE financeiro3_pagamento_comprovantes cp SET ativo=FALSE,atualizado_em=NOW()
                FROM financeiro3_pagamento_contas c
                WHERE cp.conta_id=c.id AND c.perfil_id=:perfil AND cp.ativo
            """), {"perfil": perfil["id"]})
    for arquivo in arquivos:
        numero = numero_conta_do_comprovante(arquivo["name"])
        with get_engine().begin() as conn:
            conta = conn.execute(text("""
                SELECT id FROM financeiro3_pagamento_contas
                WHERE perfil_id=:perfil AND numero=:numero
            """), {"perfil": perfil["id"], "numero": numero}).mappings().first() if numero else None
            if not conta:
                _registrar_erro(conn, perfil["id"], arquivo, "COMPROVANTE",
                                "Nomeie com um número de conta válido, como CP-000001.pdf.")
                contadores["erros"] += 1
                try:
                    _mover(perfil, arquivo, "contas_com_erro")
                except Exception:
                    pass
                continue
            resultado = conn.execute(text("""
                INSERT INTO financeiro3_pagamento_comprovantes
                  (conta_id,drive_file_id,nome_arquivo,mime_type,drive_web_view_link)
                VALUES (:conta,:arquivo,:nome,:mime,NULL)
                ON CONFLICT (drive_file_id) DO UPDATE SET conta_id=EXCLUDED.conta_id,
                  nome_arquivo=EXCLUDED.nome_arquivo,mime_type=EXCLUDED.mime_type,
                  drive_web_view_link=NULL,ativo=TRUE,atualizado_em=NOW()
                RETURNING (xmax=0) AS inserido
            """), {"conta": conta["id"], "arquivo": arquivo["id"], "nome": arquivo["name"],
                     "mime": Path(arquivo["name"]).suffix.lower()}).mappings().one()
            _resolver_erro(conn, perfil["id"], arquivo["id"], "COMPROVANTE")
            if resultado["inserido"]:
                contadores["comprovantes_novos"] += 1
                registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta["id"],
                                 evento="COMPROVANTE_LOCALIZADO",
                                 dados_novos={"arquivo_id": arquivo["id"], "nome": arquivo["name"]})


def _reconciliar_contas(perfil: dict, contadores: dict):
    with get_engine().connect() as conn:
        contas = [dict(item) for item in conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_contas WHERE perfil_id=:perfil ORDER BY id
        """), {"perfil": perfil["id"]}).mappings().all()]
    for conta in contas:
        if not re.fullmatch(r"[0-9a-f]{32}", conta["drive_file_id"] or ""):
            continue
        try:
            arquivo = localizar_arquivo(perfil, conta["drive_file_id"])
            if not arquivo:
                raise PagamentosStorageErro("Arquivo não encontrado no armazenamento.")
            destino_status = "QUITADAS" if conta_pronta_para_quitadas(conta) else "CONTROLADAS"
            destino_pasta = "contas_quitadas" if destino_status == "QUITADAS" else "contas_controladas"
            atualizado = _mover(perfil, arquivo, destino_pasta, nome_controlado(conta))
            status = "AGUARDANDO_OM" if conta["status_reembolso"] == "REEMBOLSADA" and not conta.get("numero_om") else "OK"
            mudou = conta["pasta_atual"] != destino_status or conta["drive_nome_atual"] != atualizado["name"]
            _atualizar_arquivo_conta(conta, atualizado, destino_status, status)
            contadores["arquivos_movidos"] += int(mudou)
        except Exception as exc:
            _atualizar_arquivo_conta(conta, conta, "PENDENTE_MOVIMENTACAO", "ERRO", str(exc))
            contadores["erros"] += 1


def sincronizar_perfil(perfil_id: int, *, origem="AUTOMATICA", usuario_id=None) -> dict:
    origem = origem.upper()
    if origem not in {"AUTOMATICA", "MANUAL"}:
        raise ValueError("Origem de sincronização inválida.")
    engine = get_engine()
    with engine.begin() as conn:
        perfil = conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_perfis WHERE id=:id AND ativo
        """), {"id": perfil_id}).mappings().first()
        if not perfil:
            raise PagamentosStorageErro("Perfil de pagamentos não encontrado ou inativo.")
        execucao_id = conn.execute(text("""
            INSERT INTO financeiro3_pagamento_sincronizacoes(perfil_id,origem,executado_por)
            VALUES (:perfil,:origem,:usuario) RETURNING id
        """), {"perfil": perfil_id, "origem": origem, "usuario": usuario_id}).scalar_one()
        perfil = dict(perfil)
    contadores = {"contas_novas": 0, "comprovantes_novos": 0, "arquivos_movidos": 0, "erros": 0}
    try:
        configuracao_bucket()
        _sincronizar_novas(perfil, contadores)
        _sincronizar_comprovantes(perfil, contadores)
        _reconciliar_contas(perfil, contadores)
        status = "PARCIAL" if contadores["erros"] else "SUCESSO"
        mensagem = None if not contadores["erros"] else "Alguns arquivos exigem correção ou nova tentativa."
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE financeiro3_pagamento_perfis SET status_conexao='ATIVA',ultimo_erro=NULL,
                  ultima_sincronizacao_em=NOW(),atualizado_em=NOW() WHERE id=:id
            """), {"id": perfil_id})
            conn.execute(text("""
                UPDATE financeiro3_pagamento_sincronizacoes SET status=:status,
                  contas_novas=:contas_novas,comprovantes_novos=:comprovantes_novos,
                  arquivos_movidos=:arquivos_movidos,erros=:erros,mensagem=:mensagem,
                  concluido_em=NOW() WHERE id=:id
            """), {**contadores, "status": status, "mensagem": mensagem, "id": execucao_id})
        return {**contadores, "status": status, "perfil": perfil["nome"]}
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE financeiro3_pagamento_perfis SET status_conexao='ERRO',ultimo_erro=:erro,
                  ultima_sincronizacao_em=NOW(),atualizado_em=NOW() WHERE id=:id
            """), {"erro": str(exc), "id": perfil_id})
            conn.execute(text("""
                UPDATE financeiro3_pagamento_sincronizacoes SET status='ERRO',erros=:erros,
                  mensagem=:erro,concluido_em=NOW() WHERE id=:id
            """), {"erros": max(1, contadores["erros"]), "erro": str(exc), "id": execucao_id})
        raise


def sincronizar_todos() -> list[dict]:
    with get_engine().connect() as conn:
        ids = list(conn.execute(text(
            "SELECT id FROM financeiro3_pagamento_perfis WHERE ativo ORDER BY id"
        )).scalars())
    resultados = []
    for perfil_id in ids:
        try:
            resultados.append(sincronizar_perfil(perfil_id, origem="AUTOMATICA"))
        except Exception as exc:
            resultados.append({"perfil_id": perfil_id, "status": "ERRO", "erro": str(exc)})
    return resultados


def sincronizar_arquivo_da_conta(conta_id: int) -> None:
    with get_engine().connect() as conn:
        conta = conn.execute(text("""
            SELECT c.*,p.storage_prefix,p.id AS perfil_storage_id
            FROM financeiro3_pagamento_contas c
            JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
            WHERE c.id=:id AND p.ativo
        """), {"id": conta_id}).mappings().first()
    if not conta:
        return
    conta = dict(conta)
    perfil = {"id": conta["perfil_storage_id"], "storage_prefix": conta.get("storage_prefix")}
    try:
        arquivo = localizar_arquivo(perfil, conta["drive_file_id"])
        if not arquivo:
            raise PagamentosStorageErro("Arquivo não encontrado no armazenamento.")
        destino_status = "QUITADAS" if conta_pronta_para_quitadas(conta) else "CONTROLADAS"
        destino_pasta = "contas_quitadas" if destino_status == "QUITADAS" else "contas_controladas"
        atualizado = _mover(perfil, arquivo, destino_pasta, nome_controlado(conta))
        status = "AGUARDANDO_OM" if conta["status_reembolso"] == "REEMBOLSADA" and not conta.get("numero_om") else "OK"
        _atualizar_arquivo_conta(conta, atualizado, destino_status, status)
    except Exception as exc:
        _atualizar_arquivo_conta(conta, conta, "PENDENTE_MOVIMENTACAO", "ERRO", str(exc))
