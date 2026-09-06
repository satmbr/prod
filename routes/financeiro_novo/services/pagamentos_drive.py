import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import text

from db import get_engine
from routes.financeiro_novo.services.auditoria import registrar_evento


PASTAS = {
    "pasta_novas_id": "novas_contas",
    "pasta_controladas_id": "contas_controladas",
    "pasta_quitadas_id": "contas_quitadas",
    "pasta_comprovantes_id": "comprovantes",
    "pasta_erros_id": "contas_com_erro",
}
STATUS_PAGAMENTO = {"ABERTA", "PAGA"}
STATUS_REEMBOLSO = {"PENDENTE", "REEMBOLSADA"}
TIPOS_ACEITOS = {"application/pdf", "image/jpeg", "image/png"}
EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png"}


class PagamentosDriveErro(RuntimeError):
    pass


class NomeContaInvalido(ValueError):
    pass


@dataclass(frozen=True)
class ContaImportada:
    valor: Decimal
    data_documento: date
    data_vencimento: date
    descricao: str
    status_pagamento: str
    status_reembolso: str
    extensao: str


def extrair_id_pasta(valor: str) -> str:
    valor = (valor or "").strip()
    if not valor:
        raise ValueError("Informe o link da pasta compartilhada no Google Drive.")
    correspondencia = re.search(r"/folders/([A-Za-z0-9_-]+)", valor)
    pasta_id = correspondencia.group(1) if correspondencia else valor.split("?")[0].strip("/ ")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,180}", pasta_id):
        raise ValueError("O link ou ID da pasta do Google Drive é inválido.")
    return pasta_id


def _decimal_nome(valor: str) -> Decimal:
    texto = valor.strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise NomeContaInvalido("O primeiro campo deve ser um valor, como 100,50.") from exc
    if not numero.is_finite() or numero <= 0:
        raise NomeContaInvalido("O valor da conta deve ser maior que zero.")
    return numero


def _data_nome(valor: str, rotulo: str) -> date:
    try:
        return datetime.strptime(valor, "%d.%m.%Y").date()
    except ValueError as exc:
        raise NomeContaInvalido(f"{rotulo} deve usar o formato DD.MM.AAAA.") from exc


def interpretar_nome_conta(nome_arquivo: str) -> ContaImportada:
    extensao = Path(nome_arquivo).suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise NomeContaInvalido("Use arquivos PDF, JPG, JPEG ou PNG.")
    partes = Path(nome_arquivo).stem.split()
    if partes and re.fullmatch(r"CP-\d{6,}", partes[0], re.IGNORECASE):
        partes = partes[1:]
    if len(partes) < 6:
        raise NomeContaInvalido(
            "Use: VALOR DATA_DOCUMENTO VENCIMENTO DESCRICAO ABERTA|PAGA PENDENTE|REEMBOLSADA."
        )
    status_pagamento = partes[-2].upper()
    status_reembolso = partes[-1].upper()
    if status_pagamento not in STATUS_PAGAMENTO:
        raise NomeContaInvalido("O status de pagamento deve ser ABERTA ou PAGA.")
    if status_reembolso not in STATUS_REEMBOLSO:
        raise NomeContaInvalido("O status de reembolso deve ser PENDENTE ou REEMBOLSADA.")
    descricao = " ".join(partes[3:-2]).strip()
    if not descricao:
        raise NomeContaInvalido("Informe a descrição entre as datas e os status.")
    if len(descricao) > 220:
        raise NomeContaInvalido("A descrição deve ter até 220 caracteres.")
    data_documento = _data_nome(partes[1], "A data do documento")
    data_vencimento = _data_nome(partes[2], "A data de vencimento")
    if data_vencimento < data_documento:
        raise NomeContaInvalido("A data de vencimento não pode ser anterior à data do documento.")
    return ContaImportada(
        valor=_decimal_nome(partes[0]),
        data_documento=data_documento,
        data_vencimento=data_vencimento,
        descricao=descricao,
        status_pagamento=status_pagamento,
        status_reembolso=status_reembolso,
        extensao=extensao,
    )


def formatar_valor_nome(valor) -> str:
    numero = Decimal(valor).quantize(Decimal("0.01"))
    texto = f"{numero:,.2f}"
    return texto.replace(",", "_").replace(".", ",").replace("_", ".")


def nome_controlado(conta: dict, extensao: str | None = None) -> str:
    extensao = (extensao or Path(conta.get("drive_nome_atual") or "").suffix or ".pdf").lower()
    if extensao not in EXTENSOES_ACEITAS:
        extensao = ".pdf"
    descricao = re.sub(r"\s+", " ", conta["descricao"]).strip()
    return (
        f"{conta['numero']} {formatar_valor_nome(conta['valor'])} "
        f"{conta['data_documento'].strftime('%d.%m.%Y')} "
        f"{conta['data_vencimento'].strftime('%d.%m.%Y')} {descricao} "
        f"{conta['status_pagamento']} {conta['status_reembolso']}{extensao}"
    )


def numero_conta_do_comprovante(nome_arquivo: str) -> str | None:
    correspondencia = re.match(r"^(CP-\d{6,})(?:\s|__|\.|$)", nome_arquivo.strip(), re.IGNORECASE)
    return correspondencia.group(1).upper() if correspondencia else None


def conta_pronta_para_quitadas(conta: dict) -> bool:
    return (
        conta["status_pagamento"] == "PAGA"
        and conta["status_reembolso"] == "REEMBOLSADA"
        and bool((conta.get("numero_om") or "").strip())
    )


def email_conta_servico() -> str | None:
    try:
        return _credenciais_info().get("client_email")
    except PagamentosDriveErro:
        return None


def _credenciais_info() -> dict:
    bruto = (os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    arquivo = (os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip()
    if arquivo:
        try:
            return json.loads(Path(arquivo).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PagamentosDriveErro("Não foi possível ler GOOGLE_SERVICE_ACCOUNT_FILE.") from exc
    if not bruto:
        raise PagamentosDriveErro("Configure GOOGLE_SERVICE_ACCOUNT_JSON no Railway.")
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        try:
            return json.loads(base64.b64decode(bruto).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PagamentosDriveErro("GOOGLE_SERVICE_ACCOUNT_JSON não contém um JSON válido.") from exc


def _drive():
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise PagamentosDriveErro("As bibliotecas do Google Drive não estão instaladas.") from exc
    credenciais = Credentials.from_service_account_info(
        _credenciais_info(), scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credenciais, cache_discovery=False)


def _escapar_query(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace("'", "\\'")


def _listar_arquivos(drive, pasta_id: str) -> list[dict]:
    encontrados = []
    token = None
    consulta = f"'{_escapar_query(pasta_id)}' in parents and trashed=false"
    while True:
        resposta = drive.files().list(
            q=consulta,
            spaces="drive",
            fields="nextPageToken,files(id,name,mimeType,webViewLink,parents,modifiedTime)",
            pageToken=token,
            pageSize=1000,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        encontrados.extend(
            item for item in resposta.get("files", [])
            if item.get("mimeType") != "application/vnd.google-apps.folder"
        )
        token = resposta.get("nextPageToken")
        if not token:
            return encontrados


def _garantir_pasta(drive, raiz_id: str, nome: str) -> str:
    consulta = (
        f"'{_escapar_query(raiz_id)}' in parents and "
        f"name='{_escapar_query(nome)}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    resposta = drive.files().list(
        q=consulta, spaces="drive", fields="files(id,name)", pageSize=10,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    pastas = resposta.get("files", [])
    if pastas:
        return pastas[0]["id"]
    criada = drive.files().create(
        body={"name": nome, "mimeType": "application/vnd.google-apps.folder", "parents": [raiz_id]},
        fields="id", supportsAllDrives=True,
    ).execute()
    return criada["id"]


def _mover_arquivo(drive, arquivo: dict, destino_id: str, novo_nome: str | None = None) -> dict:
    atual = drive.files().get(
        fileId=arquivo["id"], fields="id,name,parents,webViewLink,mimeType",
        supportsAllDrives=True,
    ).execute()
    corpo = {"name": novo_nome} if novo_nome and atual.get("name") != novo_nome else None
    pais = atual.get("parents", [])
    parametros = {
        "fileId": arquivo["id"], "fields": "id,name,parents,webViewLink,mimeType",
        "supportsAllDrives": True,
    }
    if destino_id not in pais:
        parametros["addParents"] = destino_id
        if pais:
            parametros["removeParents"] = ",".join(pais)
    if corpo or "addParents" in parametros:
        parametros["body"] = corpo or {}
        return drive.files().update(**parametros).execute()
    return atual


def _registrar_erro(conn, perfil_id: int, arquivo: dict, tipo: str, mensagem: str):
    conn.execute(text("""
        INSERT INTO financeiro3_pagamento_importacao_erros
          (perfil_id,drive_file_id,tipo,nome_arquivo,drive_web_view_link,mensagem)
        VALUES (:perfil,:arquivo,:tipo,:nome,:link,:mensagem)
        ON CONFLICT (perfil_id,drive_file_id,tipo) DO UPDATE SET
          nome_arquivo=EXCLUDED.nome_arquivo,
          drive_web_view_link=EXCLUDED.drive_web_view_link,
          mensagem=EXCLUDED.mensagem,resolvido=FALSE,resolvido_em=NULL,
          ultima_ocorrencia_em=NOW()
    """), {"perfil": perfil_id, "arquivo": arquivo["id"], "tipo": tipo,
             "nome": arquivo.get("name") or "", "link": arquivo.get("webViewLink"),
             "mensagem": mensagem})


def _resolver_erro(conn, perfil_id: int, arquivo_id: str, tipo: str):
    conn.execute(text("""
        UPDATE financeiro3_pagamento_importacao_erros
        SET resolvido=TRUE,resolvido_em=NOW(),ultima_ocorrencia_em=NOW()
        WHERE perfil_id=:perfil AND drive_file_id=:arquivo AND tipo=:tipo AND NOT resolvido
    """), {"perfil": perfil_id, "arquivo": arquivo_id, "tipo": tipo})


def _criar_ou_obter_conta(perfil: dict, arquivo: dict, dados: ContaImportada) -> tuple[dict, bool]:
    engine = get_engine()
    with engine.begin() as conn:
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
            VALUES (:perfil,:arquivo,:nome,:nome,:link,:mime,:valor,:documento,:vencimento,
                    :descricao,:pagamento,:reembolso,:data_pagamento,
                    :data_reembolso,:status_sincronizacao)
            RETURNING *
        """), {"perfil": perfil["id"], "arquivo": arquivo["id"], "nome": arquivo["name"],
                 "link": arquivo.get("webViewLink"), "mime": arquivo.get("mimeType"),
                 "valor": dados.valor, "documento": dados.data_documento,
                 "vencimento": dados.data_vencimento, "descricao": dados.descricao,
                 "pagamento": dados.status_pagamento, "reembolso": dados.status_reembolso,
                 "data_pagamento": date.today() if dados.status_pagamento == "PAGA" else None,
                 "data_reembolso": date.today() if dados.status_reembolso == "REEMBOLSADA" else None,
                 "status_sincronizacao": (
                     "AGUARDANDO_OM" if dados.status_reembolso == "REEMBOLSADA" else "PENDENTE"
                 )}).mappings().one()
        numero = f"CP-{conta['id']:06d}"
        conta = conn.execute(text("""
            UPDATE financeiro3_pagamento_contas SET numero=:numero WHERE id=:id RETURNING *
        """), {"numero": numero, "id": conta["id"]}).mappings().one()
        _resolver_erro(conn, perfil["id"], arquivo["id"], "CONTA")
        registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta["id"],
                         evento="IMPORTADA_DRIVE", dados_novos=dict(conta))
        return dict(conta), True


def _atualizar_arquivo_conta(conta: dict, arquivo: dict, destino: str, status: str, erro: str | None = None):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE financeiro3_pagamento_contas SET drive_nome_atual=:nome,
              drive_web_view_link=COALESCE(:link,drive_web_view_link),pasta_atual=:pasta,
              status_sincronizacao=:status,ultimo_erro=:erro,atualizado_em=NOW()
            WHERE id=:id
        """), {"nome": arquivo.get("name", conta["drive_nome_atual"]),
                 "link": arquivo.get("webViewLink"), "pasta": destino,
                 "status": status, "erro": erro, "id": conta["id"]})


def _sincronizar_novas(drive, perfil: dict, contadores: dict):
    for arquivo in _listar_arquivos(drive, perfil["pasta_novas_id"]):
        try:
            if arquivo.get("mimeType") not in TIPOS_ACEITOS and Path(arquivo["name"]).suffix.lower() not in EXTENSOES_ACEITAS:
                raise NomeContaInvalido("Use arquivos PDF, JPG, JPEG ou PNG.")
            dados = interpretar_nome_conta(arquivo["name"])
            conta, criada = _criar_ou_obter_conta(perfil, arquivo, dados)
            destino = "QUITADAS" if conta_pronta_para_quitadas(conta) else "CONTROLADAS"
            pasta_id = perfil["pasta_quitadas_id"] if destino == "QUITADAS" else perfil["pasta_controladas_id"]
            movido = _mover_arquivo(drive, arquivo, pasta_id, nome_controlado(conta, dados.extensao))
            status = "AGUARDANDO_OM" if conta["status_reembolso"] == "REEMBOLSADA" and not conta.get("numero_om") else "OK"
            _atualizar_arquivo_conta(conta, movido, destino, status)
            contadores["contas_novas"] += int(criada)
            contadores["arquivos_movidos"] += 1
        except Exception as exc:
            contadores["erros"] += 1
            with get_engine().begin() as conn:
                _registrar_erro(conn, perfil["id"], arquivo, "CONTA", str(exc))
            try:
                _mover_arquivo(drive, arquivo, perfil["pasta_erros_id"])
            except Exception:
                pass


def _sincronizar_comprovantes(drive, perfil: dict, contadores: dict):
    arquivos = _listar_arquivos(drive, perfil["pasta_comprovantes_id"])
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
                _registrar_erro(
                    conn, perfil["id"], arquivo, "COMPROVANTE",
                    "Nomeie o comprovante com um número de conta válido, como CP-000001.pdf."
                )
                contadores["erros"] += 1
                continue
            resultado = conn.execute(text("""
                INSERT INTO financeiro3_pagamento_comprovantes
                  (conta_id,drive_file_id,nome_arquivo,mime_type,drive_web_view_link)
                VALUES (:conta,:arquivo,:nome,:mime,:link)
                ON CONFLICT (drive_file_id) DO UPDATE SET
                  conta_id=EXCLUDED.conta_id,nome_arquivo=EXCLUDED.nome_arquivo,
                  mime_type=EXCLUDED.mime_type,drive_web_view_link=EXCLUDED.drive_web_view_link,
                  ativo=TRUE,atualizado_em=NOW()
                RETURNING (xmax=0) AS inserido
            """), {"conta": conta["id"], "arquivo": arquivo["id"], "nome": arquivo["name"],
                     "mime": arquivo.get("mimeType"), "link": arquivo.get("webViewLink")}).mappings().one()
            _resolver_erro(conn, perfil["id"], arquivo["id"], "COMPROVANTE")
            if resultado["inserido"]:
                contadores["comprovantes_novos"] += 1
                registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta["id"],
                                 evento="COMPROVANTE_LOCALIZADO",
                                 dados_novos={"drive_file_id": arquivo["id"], "nome": arquivo["name"]})


def _reconciliar_contas(drive, perfil: dict, contadores: dict):
    with get_engine().connect() as conn:
        contas = [dict(item) for item in conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_contas WHERE perfil_id=:perfil ORDER BY id
        """), {"perfil": perfil["id"]}).mappings().all()]
    for conta in contas:
        try:
            arquivo = drive.files().get(
                fileId=conta["drive_file_id"], fields="id,name,parents,webViewLink,mimeType",
                supportsAllDrives=True,
            ).execute()
            destino = "QUITADAS" if conta_pronta_para_quitadas(conta) else "CONTROLADAS"
            pasta_id = perfil["pasta_quitadas_id"] if destino == "QUITADAS" else perfil["pasta_controladas_id"]
            atualizado = _mover_arquivo(drive, arquivo, pasta_id, nome_controlado(conta))
            status = "AGUARDANDO_OM" if conta["status_reembolso"] == "REEMBOLSADA" and not conta.get("numero_om") else "OK"
            mudou = conta["pasta_atual"] != destino or conta["drive_nome_atual"] != atualizado.get("name")
            _atualizar_arquivo_conta(conta, atualizado, destino, status)
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
            raise PagamentosDriveErro("Perfil de pagamentos não encontrado ou inativo.")
        execucao_id = conn.execute(text("""
            INSERT INTO financeiro3_pagamento_sincronizacoes(perfil_id,origem,executado_por)
            VALUES (:perfil,:origem,:usuario) RETURNING id
        """), {"perfil": perfil_id, "origem": origem, "usuario": usuario_id}).scalar_one()
        perfil = dict(perfil)
    contadores = {"contas_novas": 0, "comprovantes_novos": 0, "arquivos_movidos": 0, "erros": 0}
    try:
        drive = _drive()
        raiz = drive.files().get(
            fileId=perfil["pasta_raiz_id"], fields="id,name,mimeType,webViewLink",
            supportsAllDrives=True,
        ).execute()
        if raiz.get("mimeType") != "application/vnd.google-apps.folder":
            raise PagamentosDriveErro("O link informado não aponta para uma pasta do Google Drive.")
        ids = {campo: _garantir_pasta(drive, perfil["pasta_raiz_id"], nome) for campo, nome in PASTAS.items()}
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE financeiro3_pagamento_perfis SET pasta_novas_id=:pasta_novas_id,
                  pasta_controladas_id=:pasta_controladas_id,pasta_quitadas_id=:pasta_quitadas_id,
                  pasta_comprovantes_id=:pasta_comprovantes_id,pasta_erros_id=:pasta_erros_id,
                  status_conexao='ATIVA',ultimo_erro=NULL,atualizado_em=NOW()
                WHERE id=:id
            """), {**ids, "id": perfil_id})
        perfil.update(ids)
        _sincronizar_novas(drive, perfil, contadores)
        _sincronizar_comprovantes(drive, perfil, contadores)
        _reconciliar_contas(drive, perfil, contadores)
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
            SELECT c.*,p.pasta_controladas_id,p.pasta_quitadas_id
            FROM financeiro3_pagamento_contas c
            JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
            WHERE c.id=:id AND p.ativo
        """), {"id": conta_id}).mappings().first()
    if not conta or not conta["pasta_controladas_id"] or not conta["pasta_quitadas_id"]:
        return
    conta = dict(conta)
    try:
        drive = _drive()
        arquivo = drive.files().get(
            fileId=conta["drive_file_id"], fields="id,name,parents,webViewLink,mimeType",
            supportsAllDrives=True,
        ).execute()
        destino = "QUITADAS" if conta_pronta_para_quitadas(conta) else "CONTROLADAS"
        pasta_id = conta["pasta_quitadas_id"] if destino == "QUITADAS" else conta["pasta_controladas_id"]
        atualizado = _mover_arquivo(drive, arquivo, pasta_id, nome_controlado(conta))
        status = "AGUARDANDO_OM" if conta["status_reembolso"] == "REEMBOLSADA" and not conta.get("numero_om") else "OK"
        _atualizar_arquivo_conta(conta, atualizado, destino, status)
    except Exception as exc:
        _atualizar_arquivo_conta(conta, conta, "PENDENTE_MOVIMENTACAO", "ERRO", str(exc))
