from routes.financeiro_novo.services.valores import ValorInvalido


EMPRESAS = (
    ("MATISA", "Matisa"),
    ("PRUMO", "Prumo"),
    ("PRUMAT", "Prumat"),
)
CODIGOS_EMPRESA = dict(EMPRESAS)


def empresa_valida(valor, *, padrao="MATISA"):
    codigo = str(valor or padrao).strip().upper()
    if codigo not in CODIGOS_EMPRESA:
        raise ValorInvalido("Empresa inválida. Selecione Matisa, Prumo ou Prumat.")
    return codigo


def nome_empresa(codigo):
    return CODIGOS_EMPRESA.get(codigo, codigo)
