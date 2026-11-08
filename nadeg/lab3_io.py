"""Exports contain the student's current accepted analysis, not unaccepted AI drafts."""
import csv
from html import escape
from io import BytesIO, StringIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer

from .export import ensure_font
from .lab3 import Analysis, LABELS, ROW_FIELDS


def csv_analysis(analysis: Analysis):
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    def safe(value):
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    def row(values):
        writer.writerow([safe(str(value)) for value in values])
    row(['ЛР №3 - аналитическая часть', analysis.title])
    for label, field in [('Назначение', 'purpose'), ('Конструкция', 'construction'), ('Размещение', 'placement')]:
        row([label, getattr(analysis, field)])
    row(['Строка', *LABELS])
    for item in analysis.rows:
        row([item.id, *[getattr(item, field) for field in ROW_FIELDS]])
    row(['Вывод', analysis.conclusion])
    row(['Ограничения и недостающие данные', analysis.limitations])
    row(['Материалы'])
    for material in analysis.materials:
        row([material.id, material.name, material.text, 'Изображение в проекте JSON' if material.image else ''])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def pdf_analysis(analysis: Analysis):
    ensure_font()
    body = ParagraphStyle('lab3-body', fontName='NADEG', fontSize=10, leading=15, spaceAfter=9, wordWrap='CJK')
    heading = ParagraphStyle('lab3-heading', parent=body, fontSize=17, leading=23, textColor=colors.HexColor('#0271ff'), spaceAfter=16)
    sub = ParagraphStyle('lab3-sub', parent=body, fontSize=12, leading=17, spaceBefore=8, spaceAfter=10)
    label = ParagraphStyle('lab3-label', parent=body, fontSize=8, leading=12, textColor=colors.HexColor('#626c79'), spaceAfter=3)
    def p(text, style=body):
        return Paragraph(escape(text or 'Не заполнено').replace('\n', '<br/>'), style)
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=42, bottomMargin=42,
                            title=analysis.title, author='NADEG')
    items = [p('NADEG / Лабораторная работа №3', heading), p('Оценка мероприятий по повышению живучести. Аналитическая часть.'), p(analysis.title, sub)]
    for title, field in [('Назначение объекта', 'purpose'), ('Описание конструкции', 'construction'), ('Размещение', 'placement')]:
        items.extend([CondPageBreak(75), p(title, label), p(getattr(analysis, field))])
    items.extend([Spacer(1, 8), CondPageBreak(100), p('Анализ конструкции и предлагаемые мероприятия', sub)])
    # Vertical entries remain readable for long explanations on portrait pages.
    for index, row in enumerate(analysis.rows, 1):
        items.extend([CondPageBreak(100), p(f'{index}. Строка {row.id}', sub)])
        for title, field in zip(LABELS, ROW_FIELDS):
            items.extend([CondPageBreak(55), p(title, label), p(getattr(row, field))])
    for title, field in [('Вывод', 'conclusion'), ('Ограничения и недостающие данные', 'limitations')]:
        items.extend([CondPageBreak(95), p(title, sub), p(getattr(analysis, field))])
    if analysis.materials:
        items.extend([CondPageBreak(95), p('Исходные материалы', sub)])
        for material in analysis.materials:
            items.extend([CondPageBreak(42), p(f'{material.id}. {material.name}', label)])
            if material.text:
                items.append(p(material.text))
            if material.image:
                items.append(p('Изображение хранится в проекте JSON. В аналитический отчёт не включено.', label))
    def footer(canvas, document):
        canvas.setFont('NADEG', 8)
        canvas.setFillColor(colors.HexColor('#626c79'))
        canvas.drawString(44, 24, 'NADEG / ЛР №3 / Аналитическая часть')
        canvas.drawRightString(A4[0] - 44, 24, str(document.page))
    doc.build(items, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
