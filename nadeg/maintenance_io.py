import csv
import re
from decimal import Decimal
from io import BytesIO, StringIO
from html import escape

from pydantic import Field, field_validator, ValidationError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, CondPageBreak

from .engine import ModelError
from .export import ensure_font, short
from .maintenance import MaintenanceProblem, OPERATIONAL, Operation, Periods, validate_periods
from .models import StrictModel


class ImportRegulation(StrictModel):
    text: str = Field(min_length=1, max_length=100000)
    periods: Periods

    @field_validator("periods")
    @classmethod
    def nested_periods(cls, value):
        return validate_periods(value)


def import_regulation(request: ImportRegulation):
    text = request.text.lstrip("\ufeff")
    try:
        # Excel TSV and semicolon CSV take precedence over decimal commas.
        delimiter = ";"
        for candidate in ("\t", ";", ","):
            try:
                first = next((r for r in csv.reader(StringIO(text), delimiter=candidate, strict=True) if any(c.strip() for c in r)), [])
            except csv.Error:
                continue
            if len(first) > 1:
                delimiter = candidate
                break
        reader = csv.reader(StringIO(text), delimiter=delimiter, strict=True)
        rows = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                if rows:
                    break
                continue
            rows.append([cell.strip() for cell in row])
            if len(rows) > 101:
                raise ModelError("Максимум 100 операций в регламенте")
    except csv.Error as error:
        raise ModelError("Не удалось прочитать таблицу. Используйте CSV с ; или таблицу из Excel с табуляцией") from error
    if not rows:
        raise ModelError("Таблица пуста")
    definitions = ([{"id": key, "label": label, "interval": None} for key, label in OPERATIONAL]
                   + [{"id": p.id, "label": f"Регламент {p.interval} ч", "interval": str(p.interval)} for p in request.periods])
    keys = [f["id"] for f in definitions]
    def normalized(label):
        return re.sub(r",?\s*чел[·.\s-]*ч$", "", label.casefold().replace("ё", "е")).strip()

    aliases = {"operation": "name", "name": "name", "операция": "name", "наименование": "name", "название операции": "name"}
    for key, label in [("preliminary", "Предварительная"), ("preflight", "Предполётная"),
                       ("turnaround", "Повторный вылет"), ("postflight", "Послеполётная")]:
        aliases[normalized(label)] = key
    for f in definitions:
        for label in [f["id"], f["label"], f["label"].replace(".", ",")]:
            aliases[normalized(label)] = f["id"]
        if f["interval"]:
            val = format(Decimal(f["interval"]), "f")
            val = val.rstrip("0").rstrip(".") if "." in val else val
            for label in [val, val + "ч", val + " ч", f["interval"], f["interval"].replace(".", ",")]:
                aliases[normalized(label)] = f["id"]
    has_header = aliases.get(normalized(rows[0][0])) == "name"
    if has_header:
        header = rows.pop(0)
        try:
            columns = [aliases[normalized(label)] for label in header]
        except KeyError as error:
            raise ModelError(f"Неизвестный столбец {error.args[0]}. Используйте названия форм или их периоды")
        if len(columns) != len(set(columns)):
            raise ModelError("В таблице повторяются столбцы")
    else:
        columns = ["name", *keys]
    if not rows:
        raise ModelError("Добавьте хотя бы одну операцию после заголовков")
    if len(rows) > 100:
        raise ModelError("Максимум 100 операций в регламенте")
    operations = []
    for index, row in enumerate(rows, 1):
        if len(row) != len(columns):
            raise ModelError(f"Строка {index}: ожидается {len(columns)} ячеек, получено {len(row)}")
        values = dict(zip(columns, row))
        try:
            operation = Operation(name=values["name"], labor={key: values.get(key, "") or "0" for key in keys})
        except ValidationError as error:
            raise ModelError(f"Строка {index}: проверьте название и неотрицательные числовые трудоёмкости") from error
        operations.append(operation.model_dump(mode="json"))
    return {"operations": operations}


def csv_maintenance(problem: MaintenanceProblem, result):
    stream = StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    definitions = result["forms"]
    writer.writerow(["operation", *[f["interval"] if f["interval"] is not None else f["id"] for f in definitions]])
    for operation in problem.operations:
        name = operation.name
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow([name, *[str(operation.labor[f["id"]]) for f in definitions]])
    writer.writerow([])
    writer.writerow(["Ресурс, ч", result["resource"]])
    writer.writerow(["Время полёта, ч", result["flight_time"]])
    writer.writerow(["Полётов за день", result["flights_per_day"]])
    writer.writerow(["Лётных дней (точно)", result["flight_days_exact"]])
    writer.writerow(["Суммарная трудоёмкость, чел·ч", result["total_labor"]])
    writer.writerow(["Удельная трудоёмкость, чел·ч/ч налёта", result["specific_labor"]])
    writer.writerow([])
    writer.writerow(["Форма", "Количество", "На одно обслуживание, чел·ч", "За ресурс, чел·ч", "Доля, %"])
    for f in definitions:
        writer.writerow([f["label"], f["count"], f["per_service"], f["total"], f["share_percent"]])
    writer.writerow([])
    writer.writerow(["Операция", "За ресурс, чел·ч", "Доля, %"])
    for op in result["operations"]:
        name = op["name"]
        if name.lstrip().startswith(("=", "+", "-", "@")):
            name = "'" + name
        writer.writerow([name, op["total"], op["share_percent"]])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def pdf_maintenance(problem: MaintenanceProblem, result):
    ensure_font()
    regular = ParagraphStyle("maintenance-body", fontName="NADEG", fontSize=9, leading=14, spaceAfter=8, wordWrap="CJK")
    small = ParagraphStyle("maintenance-small", parent=regular, fontSize=8, leading=12)
    heading = ParagraphStyle("maintenance-heading", parent=regular, fontSize=16, leading=21, textColor=colors.HexColor("#0271ff"), spaceAfter=16)
    section = ParagraphStyle("maintenance-section", parent=regular, spaceBefore=8, spaceAfter=10)

    def p(value, style=regular):
        return Paragraph(escape(str(value)), style)

    def display(value, places=6):
        value = Decimal(value)
        if value and (abs(value) < Decimal("1e-6") or abs(value) >= Decimal("1e12")):
            return f"{value:.5E}"
        return f"{value:.{places}f}".rstrip("0").rstrip(".") if value else "0"

    def table(rows, widths):
        t = Table([[p(cell, small) for cell in row] for row in rows], colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2ff")),
                               ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#dce3ec")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        return t

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=42, bottomMargin=42,
                            title=problem.title, author="NADEG")
    items = [p("NADEG / Лабораторная работа №2", heading), p("Расчёт трудоёмкости технического обслуживания"), p(problem.title),
             p(f"Ресурс t₁ = {problem.resource} ч; время полёта τ = {problem.flight_time} ч; полётов за день n = {problem.flights_per_day}."),
             p(f"Лётных дней: {short(result['flight_days'])} (точное значение: {result['flight_days_exact']})."),
             p(f"Суммарная трудоёмкость: {short(result['total_labor'])} чел·ч."),
             p(f"Удельная трудоёмкость: {short(result['specific_labor'])} чел·ч/ч налёта."), Spacer(1, 8), CondPageBreak(100), p("Составляющие трудоёмкости", section)]
    items.append(table([["Вид обслуживания", "Кол-во", "На одно, чел·ч", "За ресурс, чел·ч", "Доля, %"]]
                       + [[f["label"], display(f["count"]), display(f["per_service"]), display(f["total"]), display(f["share_percent"], 2)] for f in result["forms"]],
                       [170, 65, 85, 110, 85]))
    items.extend([Spacer(1, 14), CondPageBreak(100), p("Вклад операций", section), table([["Операция", "За ресурс, чел·ч", "Доля, %"]]
                  + [[op["name"], display(op["total"]), display(op["share_percent"], 2)] for op in result["operations"]], [325, 110, 80])])
    definitions = result["forms"]
    for start in range(0, len(definitions), 3):
        group = definitions[start:start + 3]
        items.extend([Spacer(1, 16), CondPageBreak(100), p("Регламент: трудоёмкости одного обслуживания, чел·ч", section),
                      table([["Операция", *[f["label"] for f in group]]]
                            + [[op.name, *[short(op.labor[f["id"]]) for f in group]] for op in problem.operations],
                            [215, *([300 / len(group)] * len(group))])])
    items.extend([Spacer(1, 16), CondPageBreak(100), p("Формулы и правила", section), p("Nлд = t₁ / (nτ); Nпредв = Nлд / 2; Nпредпол = Nпослепол = Nлд; Nповт = Nлд(n − 1).", small),
                  p("Для периода p: C(p) = ceil(t₁/p) − 1. Количество отдельных младших форм: N(p) = C(p) − C(следующего периода).", small),
                  p("Tⱼ = Nⱼ × Σᵢtᵢⱼ; Tпл = ΣⱼTⱼ; Kт.пл = Tпл / t₁.", small)])
    for note in [*result["rules"], *result["warnings"]]:
        items.append(p(note, small))

    def footer(canvas, document):
        canvas.setFont("NADEG", 8)
        canvas.setFillColor(colors.HexColor("#616873"))
        canvas.drawString(40, 24, "NADEG · ЛР №2 · Учебный расчёт")
        canvas.drawRightString(A4[0] - 40, 24, str(document.page))

    doc.build(items, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
