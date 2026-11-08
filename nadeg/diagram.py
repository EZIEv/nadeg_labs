from html import escape


def layout(tree, reserves):
    """Return shared vector primitives for SVG and PDF."""
    if isinstance(tree, str):
        count = reserves.get(tree, 0) + 1
        height = max(64, count * 42 + 16)
        box_width = max(106, (len(tree) + (3 if count > 1 else 0)) * 8 + 16)
        width = box_width + 50
        shapes = []
        center = height / 2
        for i in range(count):
            y = 14 + i * 42 if count > 1 else center - 16
            cy = y + 16
            shapes.extend([("line", 0, center, 14, center), ("line", 14, center, 14, cy),
                           ("line", 14, cy, 25, cy), ("rect", 25, y, box_width, 32),
                           ("text", 25 + box_width / 2, cy + 4, f"{tree}.{i + 1}" if count > 1 else tree),
                           ("line", width - 25, cy, width - 14, cy),
                           ("line", width - 14, cy, width - 14, center), ("line", width - 14, center, width, center)])
        return width, height, shapes
    left = layout(tree[1], reserves)
    right = layout(tree[2], reserves)
    shapes = []

    def place(drawing, x, y):
        for kind, *values in drawing[2]:
            if kind == "line":
                x1, y1, x2, y2 = values
                shapes.append((kind, x1 + x, y1 + y, x2 + x, y2 + y))
            elif kind == "rect":
                xx, yy, w, h = values
                shapes.append((kind, xx + x, yy + y, w, h))
            else:
                xx, yy, text = values
                shapes.append((kind, xx + x, yy + y, text))

    if tree[0] == "and":
        w, h = left[0] + right[0] + 24, max(left[1], right[1])
        place(left, 0, (h - left[1]) / 2)
        place(right, left[0] + 24, (h - right[1]) / 2)
        shapes.append(("line", left[0], h / 2, left[0] + 24, h / 2))
    else:
        w, h = max(left[0], right[0]) + 64, left[1] + right[1] + 22
        place(left, 32, 0)
        place(right, 32, left[1] + 22)
        y1, y2 = left[1] / 2, left[1] + 22 + right[1] / 2
        shapes.extend([("line", 0, h / 2, 16, h / 2), ("line", 16, y1, 16, y2),
                       ("line", w - 16, y1, w - 16, y2), ("line", w - 16, h / 2, w, h / 2)])
        for y, child in [(y1, left), (y2, right)]:
            shapes.extend([("line", 16, y, 32, y), ("line", 32 + child[0], y, w - 16, y)])
    return w, h, shapes


def svg(tree, elements):
    w, h, shapes = layout(tree, {e["id"]: e["reserves"] for e in elements})
    content = []
    for kind, *v in shapes:
        if kind == "line":
            content.append(f'<line x1="{v[0]}" y1="{v[1]}" x2="{v[2]}" y2="{v[3]}" stroke="#616873"/>')
        elif kind == "rect":
            content.append(f'<rect x="{v[0]}" y="{v[1]}" width="{v[2]}" height="{v[3]}" rx="3" fill="#ffffff" stroke="#0271ff"/>')
        else:
            content.append(f'<text x="{v[0]}" y="{v[1]}" font-size="12" font-family="Arial,sans-serif" text-anchor="middle" fill="#232323">{escape(v[2])}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="diagram-title" '
            f'viewBox="-16 -16 {w + 32} {h + 32}" width="{w + 32}" height="{h + 32}">'
            '<title id="diagram-title">Структурная диаграмма. A.1, A.2 — разные копии группы A; повторные обозначения — общие физические элементы.</title>'
            f'<rect x="-16" y="-16" width="{w + 32}" height="{h + 32}" fill="#ffffff"/>' + "".join(content) + '</svg>')
