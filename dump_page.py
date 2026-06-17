"""Dump structured PDF page data to JSON for construction analysis.
Usage: uv run python dump_page.py <pdf> <page>
"""
import sys, orjson, fitz

def to_hex(c):
    if c is None:
        return None
    return "#{:02x}{:02x}{:02x}".format(int(c[0]*255), int(c[1]*255), int(c[2]*255))

def r1(v):
    return round(v, 1)

def serialize_item(item):
    op = item[0]
    if op == "l":
        return [op, [r1(item[1].x), r1(item[1].y)], [r1(item[2].x), r1(item[2].y)]]
    if op == "c":
        return [op, [r1(item[1].x), r1(item[1].y)], [r1(item[2].x), r1(item[2].y)],
                [r1(item[3].x), r1(item[3].y)], [r1(item[4].x), r1(item[4].y)]]
    if op == "re":
        r = item[1]
        return [op, r1(r.x0), r1(r.y0), r1(r.x1), r1(r.y1)]
    if op == "qu":
        q = item[1]
        return [op, [r1(q.ul.x), r1(q.ul.y)], [r1(q.ur.x), r1(q.ur.y)],
                [r1(q.ll.x), r1(q.ll.y)], [r1(q.lr.x), r1(q.lr.y)]]
    return list(item)

def is_noise(d):
    rect = d["rect"]
    area = (rect.x1 - rect.x0) * (rect.y1 - rect.y0)
    # white strokes — rendering artifact in any PDF
    if d["color"] == (1.0, 1.0, 1.0) and d["fill"] is None:
        return True
    # zero-area paths with no fill — invisible sub-pixel lines
    if area < 0.01 and d["fill"] is None:
        return True
    return False

def slim_drawing(d):
    out = {
        "type": d["type"],
        "rect": [r1(v) for v in d["rect"]],
        "items": [serialize_item(i) for i in d["items"]],
    }
    if d["color"] is not None:
        out["color"] = to_hex(d["color"])
    if d["fill"] is not None:
        out["fill"] = to_hex(d["fill"])
    if d["width"] is not None:
        out["width"] = round(d["width"], 3)
    return out

def get_hidden_texts(page):
    """Collect text content that is white (hidden metadata)."""
    hidden = set()
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["color"] == 16777215:  # white
                    hidden.add(s["text"].strip())
    return hidden

pdf, page_n = sys.argv[1], int(sys.argv[2])
doc = fitz.open(pdf)
page = doc[page_n - 1]

hidden_texts = get_hidden_texts(page)

words = [
    {"text": w[4], "bbox": [r1(v) for v in w[:4]]}
    for w in page.get_text("words")
    if w[4].strip() not in hidden_texts
]

drawings = [slim_drawing(d) for d in page.get_drawings() if not is_noise(d)]

out = {
    "meta": {"page": page_n, "rect": [r1(v) for v in page.rect], "rotation": page.rotation},
    "words": words,
    "drawings": drawings,
}

path = f"page_{page_n}.json"
with open(path, "wb") as f:
    f.write(orjson.dumps(out, option=orjson.OPT_NON_STR_KEYS))

kept = len(drawings)
total = sum(1 for d in page.get_drawings())
size_mb = __import__("os").path.getsize(path) / 1e6
print(f"Written {path} ({size_mb:.1f} MB) — {kept}/{total} drawings kept, {len(words)} words")
doc.close()
