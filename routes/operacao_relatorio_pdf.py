from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from routes.operacao_producao import calcular_atraso_equivalente


NAVY = colors.HexColor("#16324F")
BLUE = colors.HexColor("#246B9E")
TEAL = colors.HexColor("#16847A")
MINT = colors.HexColor("#DDF3EC")
ORANGE = colors.HexColor("#E47A2E")
AMBER = colors.HexColor("#F1B84B")
RED = colors.HexColor("#B42318")
INK = colors.HexColor("#263746")
SLATE = colors.HexColor("#617487")
PALE = colors.HexColor("#F3F7FA")
GRID = colors.HexColor("#D8E2EA")
WHITE = colors.white


def _n(valor):
    return float(valor or 0)


def _fmt_num(valor):
    return f"{_n(valor):,.0f}".replace(",", ".")


def _fmt_decimal(valor):
    return f"{_n(valor):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_data(valor):
    if isinstance(valor, str):
        try:
            valor = date.fromisoformat(valor)
        except ValueError:
            return valor
    return valor.strftime("%d/%m/%Y") if valor else "-"


def _iso(valor):
    return valor.isoformat() if hasattr(valor, "isoformat") else str(valor)


def _snapshot(dashboard, data_referencia):
    linhas_ate_data = [
        item for item in dashboard["diario"] if item["data"] <= data_referencia
    ]
    linha_dia = next(
        (item for item in dashboard["diario"] if item["data"] == data_referencia),
        None,
    )
    ultima = linhas_ate_data[-1] if linhas_ate_data else None
    planejado_acumulado = _n(ultima["planejado_acumulado"]) if ultima else 0
    realizado_acumulado = _n(ultima["renovacao_acumulada"]) if ultima else 0
    meta = _n(dashboard["kpis"]["meta"])
    planejados_desc = [
        _n(item["planejado"])
        for item in reversed(linhas_ate_data)
        if _n(item["planejado"]) > 0
    ]
    atraso = calcular_atraso_equivalente(
        max(0, planejado_acumulado - realizado_acumulado),
        planejados_desc,
    )
    saldos = (
        dict(ultima["saldos"])
        if ultima
        else dict(dashboard["saldo_inicial"]["valores"])
    )
    impactos = [
        item for item in dashboard["impactos"] if _iso(item["data"]) == data_referencia
    ]
    patio = [
        item for item in dashboard["patio"] if _iso(item["data"]) == data_referencia
    ]
    return {
        "linha_dia": linha_dia or {},
        "planejado_dia": _n(linha_dia["planejado"]) if linha_dia else 0,
        "realizado_dia": _n(linha_dia["RENOVACAO"]) if linha_dia else 0,
        "planejado_acumulado": planejado_acumulado,
        "realizado_acumulado": realizado_acumulado,
        "desvio": realizado_acumulado - planejado_acumulado,
        "meta": meta,
        "backlog": max(0, meta - realizado_acumulado),
        "percentual": realizado_acumulado / meta * 100 if meta else 0,
        "atraso": atraso,
        "saldos": saldos,
        "impactos": impactos,
        "minutos_impacto": sum(int(item["minutos_perdidos"] or 0) for item in impactos),
        "patio": patio,
    }


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "titulo",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=21,
            textColor=NAVY,
            spaceAfter=4,
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=NAVY,
            spaceBefore=5,
            spaceAfter=6,
        ),
        "normal": ParagraphStyle(
            "normal",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=INK,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=6.4,
            leading=8,
            textColor=INK,
        ),
        "white": ParagraphStyle(
            "white",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=8,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "card_label": ParagraphStyle(
            "card_label",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=6.5,
            leading=8,
            textColor=SLATE,
            alignment=TA_LEFT,
        ),
        "card_value": ParagraphStyle(
            "card_value",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=17,
            textColor=NAVY,
            alignment=TA_LEFT,
        ),
        "right": ParagraphStyle(
            "right",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7,
            leading=9,
            textColor=INK,
            alignment=TA_RIGHT,
        ),
    }


def _cabecalho_rodape(canvas, doc, nome_eh, data_referencia, logo_path):
    largura, altura = landscape(A4)
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, altura - 22 * mm, largura, 22 * mm, fill=1, stroke=0)
    canvas.setFillColor(TEAL)
    canvas.rect(0, altura - 24 * mm, largura, 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(13 * mm, altura - 10 * mm, "DIÁRIO DE RENOVAÇÃO | P190")
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(13 * mm, altura - 16 * mm, nome_eh)
    canvas.drawRightString(
        largura - 46 * mm,
        altura - 13 * mm,
        f"Referência: {_fmt_data(data_referencia)}",
    )
    if logo_path.exists():
        canvas.drawImage(
            str(logo_path),
            largura - 39 * mm,
            altura - 19 * mm,
            width=27 * mm,
            height=12 * mm,
            preserveAspectRatio=True,
            mask="auto",
            anchor="c",
        )
    canvas.setStrokeColor(GRID)
    canvas.line(12 * mm, 10 * mm, largura - 12 * mm, 10 * mm)
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(
        12 * mm,
        6 * mm,
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | Fonte: apontamentos do sistema",
    )
    canvas.drawRightString(
        largura - 12 * mm,
        6 * mm,
        f"Página {doc.page}",
    )
    canvas.restoreState()


def _card(label, value, detail, estilos, accent=TEAL):
    tabela = Table(
        [
            [Paragraph(label.upper(), estilos["card_label"])],
            [Paragraph(value, estilos["card_value"])],
            [Paragraph(detail, estilos["small"])],
        ],
        colWidths=[39 * mm],
        rowHeights=[8 * mm, 9 * mm, 7 * mm],
    )
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return tabela


def _grafico_producao(diario, data_referencia):
    largura = 244 * mm
    altura = 58 * mm
    drawing = Drawing(largura, altura)
    drawing.add(Rect(0, 0, largura, altura, fillColor=WHITE, strokeColor=GRID))
    if not diario:
        drawing.add(String(12, altura / 2, "Sem produção registrada.", fillColor=SLATE))
        return drawing

    chart = VerticalBarChart()
    chart.x = 34
    chart.y = 24
    chart.height = altura - 38
    chart.width = largura - 48
    chart.data = [
        [_n(item["planejado"]) for item in diario],
        [_n(item["RENOVACAO"]) for item in diario],
    ]
    chart.categoryAxis.categoryNames = [
        f'{item["data"][8:10]}/{item["data"][5:7]}' for item in diario
    ]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 5
    chart.categoryAxis.labels.angle = 45
    chart.categoryAxis.labels.dy = -7
    chart.categoryAxis.strokeColor = GRID
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 5.5
    chart.valueAxis.strokeColor = GRID
    chart.valueAxis.gridStrokeColor = colors.HexColor("#E9EFF3")
    chart.valueAxis.visibleGrid = 1
    chart.bars[0].fillColor = colors.HexColor("#B9C8D4")
    chart.bars[0].strokeColor = colors.HexColor("#9DAFBD")
    chart.bars[1].fillColor = TEAL
    chart.bars[1].strokeColor = TEAL
    chart.barSpacing = 1
    chart.groupSpacing = 3
    drawing.add(chart)
    drawing.add(Rect(38, altura - 14, 8, 5, fillColor=colors.HexColor("#B9C8D4"), strokeColor=None))
    drawing.add(String(49, altura - 14, "Planejado", fontName="Helvetica", fontSize=6, fillColor=INK))
    drawing.add(Rect(92, altura - 14, 8, 5, fillColor=TEAL, strokeColor=None))
    drawing.add(String(103, altura - 14, "Renovação", fontName="Helvetica", fontSize=6, fillColor=INK))
    drawing.add(
        String(
            largura - 126,
            altura - 14,
            f"Referência do relatório: {_fmt_data(data_referencia)}",
            fontName="Helvetica",
            fontSize=6,
            fillColor=ORANGE,
        )
    )
    return drawing


def _tabela(dados, larguras, estilos, cabecalho=True, repetir=1, fonte=6.5):
    tabela = Table(dados, colWidths=larguras, repeatRows=repetir if cabecalho else 0)
    comandos = [
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), fonte),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
    ]
    if cabecalho:
        comandos.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ]
        )
    tabela.setStyle(TableStyle(comandos))
    return tabela


def gerar_relatorio_diario_pdf(dashboard, nome_eh, data_referencia, raiz_projeto):
    data_referencia = date.fromisoformat(data_referencia).isoformat()
    estilos = _estilos()
    snapshot = _snapshot(dashboard, data_referencia)
    arquivo = BytesIO()
    logo = Path(raiz_projeto) / "static" / "logo-prumat.png"
    doc = SimpleDocTemplate(
        arquivo,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=29 * mm,
        bottomMargin=13 * mm,
        title=f"Diário de Renovação - {nome_eh} - {_fmt_data(data_referencia)}",
        author="PRUMAT",
    )
    on_page = lambda canvas, documento: _cabecalho_rodape(
        canvas, documento, nome_eh, data_referencia, logo
    )
    story = []

    story.append(Paragraph("Visão executiva do dia", estilos["titulo"]))
    story.append(
        Paragraph(
            f"Leitura integrada da renovação, dos estoques intermediários e dos eventos da renovadora em {_fmt_data(data_referencia)}.",
            estilos["normal"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    cards = [
        _card("Planejado no dia", _fmt_num(snapshot["planejado_dia"]), "dormentes", estilos, BLUE),
        _card("Renovado no dia", _fmt_num(snapshot["realizado_dia"]), "dormentes", estilos, TEAL),
        _card("Renovado acumulado", _fmt_num(snapshot["realizado_acumulado"]), f"{_fmt_decimal(snapshot['percentual'])}% da meta", estilos, TEAL),
        _card("Desvio acumulado", f"{snapshot['desvio']:+,.0f}".replace(",", "."), "realizado menos planejado", estilos, ORANGE if snapshot["desvio"] < 0 else TEAL),
        _card("Backlog da meta", _fmt_num(snapshot["backlog"]), f"meta: {_fmt_num(snapshot['meta'])}", estilos, AMBER),
        _card("Impactos no dia", f"{_fmt_decimal(snapshot['minutos_impacto'] / 60)} h", f"atraso equivalente: {_fmt_decimal(snapshot['atraso'])} dia(s)", estilos, RED if snapshot["minutos_impacto"] else BLUE),
    ]
    story.append(Table([cards], colWidths=[44 * mm] * 6, hAlign="LEFT"))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Curva diária da EH", estilos["subtitulo"]))
    story.append(_grafico_producao(dashboard["diario"], data_referencia))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Posição física ao fim da referência", estilos["subtitulo"]))
    saldo_cells = []
    for codigo, rotulo in dashboard["saldos_definicao"]:
        valor = snapshot["saldos"].get(codigo, 0)
        cor = RED if valor < 0 else NAVY
        saldo_cells.append(
            Table(
                [
                    [Paragraph(rotulo, estilos["card_label"])],
                    [Paragraph(f'<font color="{cor.hexval()}">{_fmt_num(valor)}</font>', estilos["card_value"])],
                ],
                colWidths=[43 * mm],
                style=TableStyle(
                    [
                        ("BOX", (0, 0), (-1, -1), 0.45, GRID),
                        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                ),
            )
        )
    story.append(Table([saldo_cells], colWidths=[44 * mm] * 6))

    story.append(PageBreak())
    story.append(Paragraph("Movimentos, impactos e contexto do dia", estilos["titulo"]))
    linha = snapshot["linha_dia"]
    frentes = [
        ("Desc. novo", "DESCARREGAMENTO_NOVO"),
        ("Carreg. novo", "CARREGAMENTO_NOVO"),
        ("Rem. grampos", "REMOCAO_GRAMPOS"),
        ("Rem. galochas", "REMOCAO_GALOCHAS"),
        ("Renovação", "RENOVACAO"),
        ("Aplic. grampos", "APLICACAO_GRAMPOS"),
        ("Desc. velho", "DESCARREGAMENTO_VELHO"),
    ]
    frente_data = [[Paragraph("Etapa", estilos["white"]), Paragraph("Produção do dia", estilos["white"])]]
    frente_data.extend([[rotulo, _fmt_num(linha.get(codigo, 0))] for rotulo, codigo in frentes])
    frente_table = _tabela(frente_data, [47 * mm, 30 * mm], estilos, fonte=7)

    parte_data = [[
        Paragraph("Movimento / atividade", estilos["white"]),
        Paragraph("Início", estilos["white"]),
        Paragraph("Fim", estilos["white"]),
        Paragraph("Duração", estilos["white"]),
        Paragraph("Observação", estilos["white"]),
    ]]
    for item in dashboard["parte_diaria"]:
        minutos = int(_n(item["duracao_minutos"]))
        parte_data.append(
            [
                Paragraph(str(item["atividade"]), estilos["small"]),
                item["hora_inicio"],
                item["hora_fim"],
                f"{minutos // 60}h {minutos % 60:02d}min",
                Paragraph(item["obs"] or "-", estilos["small"]),
            ]
        )
    if len(parte_data) == 1:
        parte_data.append(["Sem movimentos registrados.", "-", "-", "-", "-"])
    parte_table = _tabela(
        parte_data,
        [55 * mm, 18 * mm, 18 * mm, 23 * mm, 67 * mm],
        estilos,
        fonte=6.5,
    )
    story.append(
        Table(
            [
                [
                    [Paragraph("Produção por etapa", estilos["subtitulo"]), frente_table],
                    [Paragraph("Parte Diária da P190", estilos["subtitulo"]), parte_table],
                ]
            ],
            colWidths=[84 * mm, 185 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]),
        )
    )
    story.append(Spacer(1, 5 * mm))

    impacto_data = [[
        Paragraph("Categoria", estilos["white"]),
        Paragraph("Frente", estilos["white"]),
        Paragraph("Tempo", estilos["white"]),
        Paragraph("Descrição", estilos["white"]),
        Paragraph("Providência / status", estilos["white"]),
    ]]
    categorias = dict(dashboard["categorias_impacto"])
    status = dict(dashboard["status_impacto"])
    for item in snapshot["impactos"]:
        impacto_data.append(
            [
                categorias.get(item["categoria"], item["categoria"]),
                item["frente"] or "Geral da EH",
                f'{item["minutos_perdidos"]} min',
                Paragraph(item["descricao"], estilos["small"]),
                Paragraph(
                    f'{item["providencia"] or "-"}<br/><b>{status.get(item["status"], item["status"])}</b>',
                    estilos["small"],
                ),
            ]
        )
    if len(impacto_data) == 1:
        impacto_data.append(["Sem impactos registrados.", "-", "-", "-", "-"])
    story.append(Paragraph("Impactos da referência", estilos["subtitulo"]))
    story.append(
        _tabela(
            impacto_data,
            [35 * mm, 38 * mm, 20 * mm, 88 * mm, 88 * mm],
            estilos,
            fonte=6.2,
        )
    )
    story.append(Spacer(1, 5 * mm))

    patio_data = [[
        Paragraph("Pátio", estilos["white"]),
        Paragraph("Classificação", estilos["white"]),
        Paragraph("Quantidade", estilos["white"]),
        Paragraph("Origem", estilos["white"]),
        Paragraph("Observação", estilos["white"]),
    ]]
    for item in snapshot["patio"]:
        patio_data.append(
            [
                item["patio"],
                "Bom (reaproveitável)" if item["classificacao"] == "BOM" else "Ruim (não aproveitável)",
                _fmt_num(item["quantidade"]),
                item["origem_eh"] or "-",
                Paragraph(item["observacao"] or "-", estilos["small"]),
            ]
        )
    if len(patio_data) == 1:
        patio_data.append(["Sem segregação registrada.", "-", "-", "-", "-"])
    story.append(Paragraph("Segregação no pátio", estilos["subtitulo"]))
    story.append(_tabela(patio_data, [43 * mm, 48 * mm, 28 * mm, 60 * mm, 90 * mm], estilos))

    story.append(PageBreak())
    story.append(Paragraph("Histórico consolidado da EH", estilos["titulo"]))
    story.append(
        Paragraph(
            f"Período registrado: {_fmt_data(dashboard['inicio'])} a {_fmt_data(dashboard['fim'])}. A linha da referência está destacada.",
            estilos["normal"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    historico = [[
        "Data", "Plan. dia", "Renov. dia", "Plan. acum.", "Renov. acum.",
        "Desvio", "Carreg.", "Rem. grampos", "Rem. galochas", "Pregação",
    ]]
    linha_referencia = None
    for indice, item in enumerate(dashboard["diario"], start=1):
        historico.append(
            [
                _fmt_data(item["data"]),
                _fmt_num(item["planejado"]),
                _fmt_num(item["RENOVACAO"]),
                _fmt_num(item["planejado_acumulado"]),
                _fmt_num(item["renovacao_acumulada"]),
                f'{item["desvio"]:+,.0f}'.replace(",", "."),
                _fmt_num(item["CARREGAMENTO_NOVO"]),
                _fmt_num(item["REMOCAO_GRAMPOS"]),
                _fmt_num(item["REMOCAO_GALOCHAS"]),
                _fmt_num(item["APLICACAO_GRAMPOS"]),
            ]
        )
        if item["data"] == data_referencia:
            linha_referencia = indice
    hist_table = _tabela(
        historico,
        [25 * mm, 23 * mm, 23 * mm, 27 * mm, 27 * mm, 23 * mm, 24 * mm, 29 * mm, 29 * mm, 25 * mm],
        estilos,
        fonte=5.6,
    )
    hist_table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 1.8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    if linha_referencia is not None:
        hist_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, linha_referencia), (-1, linha_referencia), colors.HexColor("#FFF0E5")),
                    ("TEXTCOLOR", (0, linha_referencia), (-1, linha_referencia), NAVY),
                    ("FONTNAME", (0, linha_referencia), (-1, linha_referencia), "Helvetica-Bold"),
                    ("BOX", (0, linha_referencia), (-1, linha_referencia), 0.8, ORANGE),
                ]
            )
        )
    story.append(hist_table)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    arquivo.seek(0)
    return arquivo
