from flask import Blueprint


bp = Blueprint(
    "financeiro_novo",
    __name__,
    url_prefix="/financeiro-novo",
    template_folder="../../templates/financeiro_novo",
)

from routes.financeiro_novo import views  # noqa: E402, F401
from routes.financeiro_novo import cadastros  # noqa: E402, F401
from routes.financeiro_novo import despesas  # noqa: E402, F401
from routes.financeiro_novo import missoes  # noqa: E402, F401
from routes.financeiro_novo import notas_debito  # noqa: E402, F401
from routes.financeiro_novo import relatorios  # noqa: E402, F401
