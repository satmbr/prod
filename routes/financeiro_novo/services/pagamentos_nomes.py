import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo


STATUS_PAGAMENTO = {"ABERTA", "PAGA"}
STATUS_REEMBOLSO = {"PENDENTE", "REEMBOLSADA"}
TIPOS_ACEITOS = {"application/pdf", "image/jpeg", "image/png"}
EXTENSOES_ACEITAS = {".pdf", ".jpg", ".jpeg", ".png"}


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
    if len(partes) < 2:
        raise NomeContaInvalido("Informe pelo menos o valor e a descrição da conta.")

    valor = _decimal_nome(partes.pop(0))
    datas = []
    while partes and len(datas) < 2 and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", partes[0]):
        datas.append(_data_nome(partes.pop(0), "A data informada"))

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    data_documento = datas[0] if datas else hoje
    data_vencimento = datas[1] if len(datas) == 2 else max(hoje, data_documento)

    status_pagamento = "ABERTA"
    status_reembolso = "PENDENTE"
    if partes and partes[-1].upper() in STATUS_REEMBOLSO:
        status_reembolso = partes.pop().upper()
    if partes and partes[-1].upper() in STATUS_PAGAMENTO:
        status_pagamento = partes.pop().upper()

    descricao = " ".join(partes).strip()
    if not descricao:
        raise NomeContaInvalido("Informe a descrição da conta após o valor e as datas opcionais.")
    if len(descricao) > 220:
        raise NomeContaInvalido("A descrição deve ter até 220 caracteres.")
    if data_vencimento < data_documento:
        raise NomeContaInvalido("A data de vencimento não pode ser anterior à data do documento.")
    return ContaImportada(
        valor=valor,
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
