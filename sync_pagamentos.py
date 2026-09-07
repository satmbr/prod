import json
import sys

from routes.financeiro_novo.services.pagamentos_bucket import sincronizar_todos


def main():
    resultados = sincronizar_todos()
    print(json.dumps(resultados, ensure_ascii=False, default=str))
    if any(item.get("status") == "ERRO" for item in resultados):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
