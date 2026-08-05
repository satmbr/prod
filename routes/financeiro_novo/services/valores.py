from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class ValorInvalido(ValueError):
    pass


def decimal_br(valor, *, casas=2, positivo=False):
    texto = str(valor or "").strip().replace("R$", "").replace(" ", "")
    if not texto:
        raise ValorInvalido("Informe um valor.")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation as exc:
        raise ValorInvalido("Informe um valor numérico válido.") from exc
    if not numero.is_finite() or (positivo and numero <= 0):
        raise ValorInvalido("O valor deve ser maior que zero.")
    quantizador = Decimal(1).scaleb(-casas)
    return numero.quantize(quantizador, rounding=ROUND_HALF_UP)


def data_iso(valor, rotulo):
    try:
        return date.fromisoformat(str(valor or ""))
    except ValueError as exc:
        raise ValorInvalido(f"{rotulo} é inválida.") from exc
