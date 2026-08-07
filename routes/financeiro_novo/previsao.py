import csv
import io
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from flask import Response, render_template, request
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso
from routes.financeiro_novo.views import build_subnav


ORIGENS = ("OM", "RD", "DESPESA", "REEMBOLSO", "ACERTO_RD", "NOTA_DEBITO")


def _filtros():
    hoje = date.today()
    primeiro = hoje.replace(day=1)
    ultimo = hoje.replace(day=monthrange(hoje.year, hoje.month)[1])
    try:
        inicio = data_iso(request.args.get("inicio") or primeiro.isoformat(), "Início")
        fim = data_iso(request.args.get("fim") or ultimo.isoformat(), "Fim")
    except (ValueError, ValorInvalido):
        inicio, fim = primeiro, ultimo
    if fim < inicio: inicio, fim = fim, inicio
    agrupamento = (request.args.get("agrupar") or "SEMANA").upper()
    if agrupamento not in {"DIA", "SEMANA", "MES"}: agrupamento = "SEMANA"
    fluxo = (request.args.get("fluxo") or "").upper()
    origem = (request.args.get("origem") or "").upper()
    centro = request.args.get("centro_custo_id", type=int)
    moeda = (request.args.get("moeda") or "").upper()
    busca = (request.args.get("q") or "").strip()
    situacao = (request.args.get("situacao") or "").upper()
    return {"inicio": inicio, "fim": fim, "agrupar": agrupamento, "fluxo": fluxo,
            "origem": origem, "centro": centro, "moeda": moeda, "q": busca,
            "situacao": situacao}


def _sql():
    return """
      SELECT * FROM (
        SELECT 'SAIDA'::text fluxo,'OM'::text origem,o.id,
          CASE WHEN pg.status='PAGO' THEN pg.data_pagamento ELSE pg.data_prevista_pagamento END data,
          pg.data_prevista_pagamento data_prevista,pg.data_pagamento,
          pg.tipo||' da OM '||o.numero_om descricao,p.nome_razao parte,
          cc.id centro_custo_id,cc.codigo centro,m.codigo moeda,pg.valor,o.status,
          CASE WHEN pg.status='PAGO' THEN 'REALIZADO' ELSE 'PREVISTO' END situacao
        FROM financeiro3_om_pagamentos pg JOIN financeiro3_oms o ON o.id=pg.om_id
        JOIN financeiro3_pessoas p ON p.id=o.solicitante_id
        JOIN financeiro3_centros_custo cc ON cc.id=o.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=o.moeda_id WHERE pg.status IN ('PREVISTO','PAGO')
        UNION ALL
        SELECT 'SAIDA','RD',r.id,
          CASE WHEN pg.status='PAGO' THEN pg.data_pagamento ELSE pg.data_prevista_pagamento END,
          pg.data_prevista_pagamento,pg.data_pagamento,pg.tipo||' da RD '||r.numero_rd,
          p.nome_razao,cc.id,cc.codigo,m.codigo,pg.valor,r.status,
          CASE WHEN pg.status='PAGO' THEN 'REALIZADO' ELSE 'PREVISTO' END
        FROM financeiro3_rd_pagamentos pg JOIN financeiro3_rds r ON r.id=pg.rd_id
        JOIN financeiro3_pessoas p ON p.id=r.responsavel_id
        JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE pg.status IN ('PREVISTO','PAGO')
        UNION ALL
        SELECT 'SAIDA','DESPESA',d.id,d.data_vencimento,d.data_vencimento,NULL::date,
          d.descricao,p.nome_razao parte,cc.id centro_custo_id,cc.codigo centro,m.codigo moeda,
          d.valor_total-COALESCE((SELECT SUM(pg.valor) FROM financeiro3_despesa_pagamentos pg
            WHERE pg.despesa_id=d.id AND pg.status='ATIVO'),0) valor,d.status,'PREVISTO'
        FROM financeiro3_despesas d JOIN financeiro3_pessoas p ON p.id=d.fornecedor_id
        JOIN financeiro3_centros_custo cc ON cc.id=d.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=d.moeda_id
        WHERE d.status IN ('APROVADA','PAGAMENTO_PARCIAL') AND NOT d.paga_na_origem
        UNION ALL
        SELECT 'SAIDA','DESPESA',d.id,pg.data_pagamento,d.data_vencimento,pg.data_pagamento,
          d.descricao,p.nome_razao,cc.id,cc.codigo,m.codigo,pg.valor,d.status,'REALIZADO'
        FROM financeiro3_despesa_pagamentos pg JOIN financeiro3_despesas d ON d.id=pg.despesa_id
        JOIN financeiro3_pessoas p ON p.id=d.fornecedor_id
        JOIN financeiro3_centros_custo cc ON cc.id=d.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=d.moeda_id WHERE pg.status='ATIVO' AND NOT d.paga_na_origem
        UNION ALL
        SELECT 'SAIDA','REEMBOLSO',r.id,r.data_prevista_pagamento,r.data_prevista_pagamento,NULL::date,
          r.objetivo,p.nome_razao,cc.id,cc.codigo,m.codigo,r.valor_total,r.status,'PREVISTO'
        FROM financeiro3_reembolsos r JOIN financeiro3_pessoas p ON p.id=r.favorecido_id
        JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE r.status='APROVADO' AND r.forma_liquidacao='DIRETO'
        UNION ALL
        SELECT 'SAIDA','REEMBOLSO',r.id,pg.data_pagamento,r.data_prevista_pagamento,pg.data_pagamento,
          r.objetivo,p.nome_razao,cc.id,cc.codigo,m.codigo,pg.valor,r.status,'REALIZADO'
        FROM financeiro3_reembolso_pagamentos pg JOIN financeiro3_reembolsos r ON r.id=pg.reembolso_id
        JOIN financeiro3_pessoas p ON p.id=r.favorecido_id
        JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE pg.status='ATIVO' AND r.forma_liquidacao='DIRETO'
        UNION ALL
        SELECT CASE WHEN a.tipo='REEMBOLSO' THEN 'SAIDA' ELSE 'ENTRADA' END,'ACERTO_RD',r.id,
          CASE WHEN a.status='LIQUIDADO' THEN a.data_liquidacao ELSE a.data_prevista_liquidacao END,
          a.data_prevista_liquidacao,a.data_liquidacao,'Acerto da RD '||r.numero_rd,p.nome_razao,
          cc.id,cc.codigo,m.codigo,a.valor,a.status,
          CASE WHEN a.status='LIQUIDADO' THEN 'REALIZADO' ELSE 'PREVISTO' END
        FROM financeiro3_rd_acertos a JOIN financeiro3_rds r ON r.id=a.rd_id
        JOIN financeiro3_pessoas p ON p.id=r.responsavel_id
        JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE a.status IN ('PENDENTE','LIQUIDADO')
        UNION ALL
        SELECT 'ENTRADA','NOTA_DEBITO',n.id,n.data_vencimento,n.data_vencimento,NULL::date,n.descricao,c.nome_razao,
          cc.id,cc.codigo,m.codigo,n.valor_total-COALESCE((SELECT SUM(rec.valor)
            FROM financeiro3_nd_recebimentos rec WHERE rec.nota_debito_id=n.id AND rec.status='ATIVO'),0),n.status,'PREVISTO'
        FROM financeiro3_notas_debito n JOIN financeiro3_clientes c ON c.id=n.cliente_id
        JOIN financeiro3_centros_custo cc ON cc.id=n.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=n.moeda_id
        WHERE n.status IN ('EMITIDA','RECEBIMENTO_PARCIAL')
        UNION ALL
        SELECT 'ENTRADA','NOTA_DEBITO',n.id,rec.data_recebimento,n.data_vencimento,rec.data_recebimento,
          n.descricao,c.nome_razao,cc.id,cc.codigo,m.codigo,rec.valor,n.status,'REALIZADO'
        FROM financeiro3_nd_recebimentos rec JOIN financeiro3_notas_debito n ON n.id=rec.nota_debito_id
        JOIN financeiro3_clientes c ON c.id=n.cliente_id
        JOIN financeiro3_centros_custo cc ON cc.id=n.centro_custo_id
        JOIN financeiro3_moedas m ON m.id=n.moeda_id WHERE rec.status='ATIVO'
      ) x WHERE x.valor>0 AND x.data BETWEEN :inicio AND :fim
    """


def _consultar(conn, filtros):
    condicoes, params = [], {"inicio": filtros["inicio"], "fim": filtros["fim"]}
    if filtros["fluxo"] in {"ENTRADA", "SAIDA"}:
        condicoes.append("x.fluxo=:fluxo"); params["fluxo"] = filtros["fluxo"]
    if filtros["origem"] in ORIGENS:
        condicoes.append("x.origem=:origem"); params["origem"] = filtros["origem"]
    if filtros["centro"]:
        condicoes.append("x.centro_custo_id=:centro"); params["centro"] = filtros["centro"]
    if filtros["moeda"]:
        condicoes.append("x.moeda=:moeda"); params["moeda"] = filtros["moeda"]
    if filtros["q"]:
        condicoes.append("(LOWER(x.descricao) LIKE :q OR LOWER(x.parte) LIKE :q)"); params["q"] = f"%{filtros['q'].lower()}%"
    if filtros["situacao"] in {"PREVISTO", "REALIZADO"}:
        condicoes.append("x.situacao=:situacao"); params["situacao"] = filtros["situacao"]
    complemento = (" AND " + " AND ".join(condicoes)) if condicoes else ""
    return conn.execute(text(_sql() + complemento + " ORDER BY x.data,x.fluxo,x.origem,x.id"), params).mappings().all()


def _rotulo_periodo(data, modo):
    if modo == "DIA": return data.isoformat(), data.strftime("%d/%m/%Y")
    if modo == "MES": return data.strftime("%Y-%m"), data.strftime("%m/%Y")
    inicio = data - timedelta(days=data.weekday())
    fim = inicio + timedelta(days=6)
    return inicio.isoformat(), f"{inicio.strftime('%d/%m')}–{fim.strftime('%d/%m')}"


def _agrupar(registros, modo):
    acumulado = defaultdict(lambda: {"entradas": 0, "saidas": 0})
    rotulos = {}
    for item in registros:
        chave_data, rotulo = _rotulo_periodo(item["data"], modo)
        chave = (item["moeda"], chave_data)
        rotulos[chave] = rotulo
        campo = "entradas" if item["fluxo"] == "ENTRADA" else "saidas"
        acumulado[chave][campo] += item["valor"]
    grupos = []
    maximo = max((max(v["entradas"], v["saidas"]) for v in acumulado.values()), default=1) or 1
    for (moeda, chave_data), valores in sorted(acumulado.items()):
        grupos.append({"moeda": moeda, "chave": chave_data, "rotulo": rotulos[(moeda, chave_data)],
            **valores, "saldo": valores["entradas"] - valores["saidas"],
            "entrada_pct": float(valores["entradas"] / maximo * 100),
            "saida_pct": float(valores["saidas"] / maximo * 100)})
    return grupos


@bp.get("/previsao")
@login_required
@permission_required("financeiro_novo", "visualizar")
def previsao():
    filtros = _filtros()
    with get_engine().connect() as conn:
        registros = _consultar(conn, filtros)
        centros = conn.execute(text("SELECT id,codigo,nome FROM financeiro3_centros_custo WHERE ativo ORDER BY codigo")).mappings().all()
        moedas = conn.execute(text("SELECT codigo FROM financeiro3_moedas WHERE ativo ORDER BY codigo")).scalars().all()
    resumo = defaultdict(lambda: {"entradas": 0, "saidas": 0})
    for item in registros:
        resumo[item["moeda"]]["entradas" if item["fluxo"] == "ENTRADA" else "saidas"] += item["valor"]
    totais = [{"moeda": moeda, **valores, "saldo": valores["entradas"]-valores["saidas"]} for moeda,valores in sorted(resumo.items())]
    return render_template("financeiro_novo/previsao.html", registros=registros,
        grupos=_agrupar(registros, filtros["agrupar"]), totais=totais, filtros=filtros,
        centros=centros, moedas=moedas, origens=ORIGENS, subnav_links=build_subnav("previsao"))


@bp.get("/previsao.csv")
@login_required
@permission_required("financeiro_novo", "visualizar")
def previsao_csv():
    filtros = _filtros()
    with get_engine().connect() as conn: registros = _consultar(conn, filtros)
    out = io.StringIO(); writer = csv.writer(out, delimiter=";")
    writer.writerow(["Data do período","Data prevista","Data realizada","Situação","Fluxo","Origem","Número","Descrição","Parte","Centro","Moeda","Valor","Status"])
    for r in registros: writer.writerow([r["data"],r["data_prevista"],r["data_pagamento"],r["situacao"],r["fluxo"],r["origem"],r["id"],r["descricao"],r["parte"],r["centro"],r["moeda"],r["valor"],r["status"]])
    return Response("\ufeff"+out.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=previsao_{filtros['inicio']}_{filtros['fim']}.csv"})
