import csv
from decimal import Decimal
from html import escape
from io import BytesIO, StringIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable, KeepTogether

from .diagram import layout
from .engine import parse


def csv_report(result):
    stream = StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(["ID", "Название", "Параметр отказов (масштаб проекта)", "Масса элемента, кг", "Резервов", "Копий", "Масса группы, кг", "Вероятность отказа группы"])
    for e in result["elements"]:
        # Spreadsheet formula injection is prevented for user-supplied text.
        name = e["name"]
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow([e["id"], name, e["rate"], e["mass"], e["reserves"], e["copies"], e["group_mass"], e["group_failure_probability"]])
    writer.writerow([])
    for label, key in [("P системы", "probability"), ("Q системы", "failure_probability"), ("Масса, кг", "mass"), ("Прирост массы, кг", "mass_increase")]:
        writer.writerow([label, result[key]])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def short(number):
    d = Decimal(number)
    if d and abs(d) < Decimal("1e-8"):
        return f"{d:.6E}"
    return f"{d:.12f}".rstrip("0").rstrip(".") if d else "0"


def probability(number):
    value = short(number)
    return ("≈ " if Decimal(value) != Decimal(number) else "= ") + value


class Diagram(Flowable):
    def __init__(self, drawing, max_width, max_height=220):
        Flowable.__init__(self)
        self.w, self.h, self.shapes = drawing
        self.factor = min(1, max_width / self.w, max_height / self.h)
        self.width, self.height = self.w * self.factor, self.h * self.factor

    def draw(self):
        c = self.canv
        c.saveState()
        c.scale(self.factor, self.factor)
        c.setLineWidth(1)
        for kind, *v in self.shapes:
            if kind == "line":
                c.setStrokeColor(colors.HexColor("#616873"))
                c.line(v[0], self.h - v[1], v[2], self.h - v[3])
            elif kind == "rect":
                c.setStrokeColor(colors.HexColor("#0271ff"))
                c.setFillColor(colors.white)
                c.rect(v[0], self.h - v[1] - v[3], v[2], v[3], fill=1)
            else:
                c.setFillColor(colors.HexColor("#232323"))
                c.setFont("NADEG", 12)
                c.drawCentredString(v[0], self.h - v[1], v[2])
        c.restoreState()


def ensure_font():
    if "NADEG" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("NADEG", str(Path(__file__).parent / "assets" / "DejaVuSans.ttf")))


def pdf_report(problem, result):
    ensure_font()
    regular = ParagraphStyle("body", fontName="NADEG", fontSize=9, leading=14, spaceAfter=8, wordWrap="CJK")
    heading = ParagraphStyle("heading", parent=regular, fontSize=16, leading=21, textColor=colors.HexColor("#0271ff"), spaceAfter=16)
    small = ParagraphStyle("small", parent=regular, fontSize=7.5, leading=11)

    def p(value, style=regular):
        return Paragraph(escape(str(value)), style)

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=42, bottomMargin=42,
                            title=problem.title, author="NADEG")
    items = [p("NADEG / Лабораторная работа №1", heading), p(problem.title),
             p("Результат проверки структуры"), p(f"Время: {problem.time} ч. Масштаб параметров отказов: {problem.rate_scale} ч⁻¹."),
             p(result["formula"] + " M = Σmᵢ(kᵢ+1)."),
             p(f"Условие работоспособности: {result['expression']}"),
             p(f"P {probability(result['probability'])}; Q = {short(result['failure_probability'])}"),
             p(f"Масса: {short(result['mass'])} кг. Без резервов: {short(result['unreserved_mass'])} кг. Прирост: {short(result['mass_increase'])} кг."),
             p(f"Требование P ≥ {problem.target}: {'выполнено' if result['target_met'] else 'не выполнено'}."),
             Spacer(1, 8)]
    if problem.max_mass is not None:
        items.append(p(f"Предел массы: {problem.max_mass} кг; {'выполнен' if result['mass_limit_met'] else 'превышен'}."))
    rows = [[p(x, small) for x in ["ID / название", "ω (масштаб проекта)", "m, кг", "Резервов / копий", "Масса группы, кг"]]]
    for e in result["elements"]:
        rows.append([p(f"{e['id']} / {e['name']}", small), p(short(e['rate']), small), p(short(e['mass']), small),
                     p(f"{e['reserves']} / {e['copies']}", small), p(short(e['group_mass']), small)])
    table = Table(rows, colWidths=[175, 100, 65, 85, 90], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2ff")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#dce3ec")),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    items.extend([table, Spacer(1, 16), p("Логическая диаграмма безотказной работы")])
    tree = parse(problem.expression, {e.id for e in problem.elements})
    drawing = layout(tree, {e["id"]: e["reserves"] for e in result["elements"]})
    if min(1, 515 / drawing[0], 220 / drawing[1]) >= .55:
        items.append(Diagram(drawing, 515))
    else:
        # Split oversized diagrams by branches instead of shrinking labels to illegibility.
        pending = [tree]
        index = 0
        while pending:
            node = pending.pop(0)
            drawing = layout(node, {e["id"]: e["reserves"] for e in result["elements"]})
            if not isinstance(node, str) and min(1, 515 / drawing[0], 220 / drawing[1]) < .55:
                pending[0:0] = [node[1], node[2]]
                continue
            index += 1
            from .engine import expression_text
            items.append(KeepTogether([p(f"Фрагмент {index}: {expression_text(node)}", small), Diagram(drawing, 515)]))
        items.append(p("Связи фрагментов определяются общим условием работоспособности. Полная схема доступна в экспорте SVG.", small))
    items.extend([Spacer(1, 12), p("Допущения и замечания")])
    for warning in result["warnings"]:
        items.append(p(warning, small))
    items.append(p("Влияние элемента: прирост P при идеализации всей его резервированной группы. Масса учитывает все введённые элементы. A.1, A.2 — разные копии группы A; повторные обозначения на схеме — те же физические элементы.", small))

    def footer(canvas, document):
        canvas.setFont("NADEG", 8)
        canvas.setFillColor(colors.HexColor("#616873"))
        canvas.drawString(40, 24, "NADEG · Учебный расчёт")
        canvas.drawRightString(A4[0] - 40, 24, str(document.page))

    doc.build(items, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
