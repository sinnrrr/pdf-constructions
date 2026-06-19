"""Usage: uv run python floor_plan_extract.py <pdf> <page_number>"""
import sys, re, json, math
from collections import Counter, defaultdict
import fitz

CODE_RE    = re.compile(r'^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$')
# NxN=N calc strings appear only on spec-floor pages; detect structural dimension products
CALC_RE    = re.compile(r'^\d+[,\.]\d+x\d+[,\.]\d+=\d+[,\.]\d+$')
# Two-decimal numbers — door widths are ≤2.5 m; larger values are room dims / areas
DECIMAL_RE = re.compile(r'^\d+[,\.]\d{2}$')

# Prefixes that over-count because apartment-type codes share the same prefix.
# Filter: on pages without calc strings use "small decimal ≤ 2.5 m within 80 px";
#         on pages WITH calc strings use "calc string within 115 px".
# ponytail: only Дв confirmed problematic; extend set if other prefixes need it.
_FILTERED_PREFIXES = {'Дв'}

COL_MIN_AREA  =  1_000
COL_MAX_AREA  = 15_000
COL_MIN_COUNT = 5
COL_MAX_COUNT = 150
MAX_ASPECT    = 5.0

# ponytail: get_drawings() materializes the full list in C (~1KB/drawing dict).
# On complex A0 plans (100k+ drawings) this alone can hit 1GB. Skip when content
# stream exceeds this; upgrade path: lower-level PyMuPDF C API if one ships.
_MAX_CONTENT_BYTES = 1_500_000  # ~37k drawing ops at ~40 bytes each


def _hex(color) -> str | None:
    if color is None:
        return None
    if isinstance(color, (int, float)):
        v = int(round(color * 255))
        return f"#{v:02x}{v:02x}{v:02x}"
    if len(color) == 3:
        r, g, b = (int(round(c * 255)) for c in color)
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _detect_columns(page) -> tuple[list[dict], list[tuple[float, float]], str | None]:
    """Single pass over page drawings → (candidates, col_points, col_color).
    Skips entirely on heavy pages to avoid OOM; by_color holds compact tuples only."""
    if len(page.read_contents()) > _MAX_CONTENT_BYTES:
        return [], [], None

    by_color: dict[str, list[tuple]] = defaultdict(list)
    for d in page.get_drawings():          # list freed by refcount when loop ends
        fill = _hex(d.get("fill"))
        if fill is None or fill == "#ffffff":
            continue
        rect = d.get("rect")
        if rect is None:
            continue
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            continue
        area = w * h
        if area < 10:
            continue
        by_color[fill].append((area, max(w, h) / min(w, h), rect.x0 + w / 2, rect.y0 + h / 2))

    candidates = []
    for color, items in by_color.items():
        count      = len(items)
        avg_area   = sum(a for a, _, _, _ in items) / count
        avg_aspect = sum(r for _, r, _, _ in items) / count
        if (COL_MIN_AREA <= avg_area <= COL_MAX_AREA
                and avg_aspect <= MAX_ASPECT
                and COL_MIN_COUNT <= count <= COL_MAX_COUNT):
            candidates.append({"color": color, "count": count,
                                "avg_area": round(avg_area, 1),
                                "avg_aspect": round(avg_aspect, 2)})
    candidates.sort(key=lambda x: -x["count"])

    if not candidates:
        return [], [], None

    col_color = candidates[0]["color"]
    items     = by_color[col_color]
    big_areas = [a for a, _, _, _ in items if COL_MIN_AREA <= a <= COL_MAX_AREA]
    avg_big   = sum(big_areas) / len(big_areas) if big_areas else COL_MAX_AREA
    radius    = math.sqrt(avg_big) * 0.5

    clusters: list[tuple[float, float]] = []
    for _, _, cx, cy in sorted(items, key=lambda x: x[2]):
        for j, (kx, ky) in enumerate(clusters):
            if math.hypot(cx - kx, cy - ky) <= radius:
                clusters[j] = ((kx + cx) / 2, (ky + cy) / 2)
                break
        else:
            clusters.append((cx, cy))

    return candidates, clusters, col_color


def _is_real_label(x0: float, y0: float,
                   decimals: list, calcs: list, has_calcs: bool) -> bool:
    if has_calcs:
        return bool(calcs) and min(math.hypot(cx - x0, cy - y0) for cx, cy in calcs) <= 115
    return any(v <= 2.5 for dx, dy, v in decimals if abs(dx - x0) < 80 and abs(dy - y0) < 80)


def analyze_page(page) -> dict:
    words     = page.get_text("words")
    decimals  = [(w[0], w[1], float(w[4].strip().replace(',', '.')))
                 for w in words if DECIMAL_RE.match(w[4].strip())]
    calcs     = [(w[0], w[1]) for w in words if CALC_RE.match(w[4].strip())]
    has_calcs = bool(calcs)

    label_counts: Counter = Counter()
    label_positions: dict = defaultdict(list)

    for w in words:
        t = w[4].strip()
        if not CODE_RE.match(t):
            continue
        prefix = t.rsplit("-", 1)[0]
        if prefix in _FILTERED_PREFIXES:
            if not _is_real_label(w[0], w[1], decimals, calcs, has_calcs):
                continue
        label_counts[prefix] += 1
        label_positions[prefix].append((w[0], w[1], w[2], w[3]))

    candidates, clusters, col_color = _detect_columns(page)

    return {
        "counts":     dict(label_counts),
        "positions":  dict(label_positions),
        "col_color":  col_color,
        "col_points": clusters,
        "col_count":  len(clusters),
        "candidates": candidates,
    }


def main():
    pdf, page_num = sys.argv[1], int(sys.argv[2])
    doc = fitz.open(pdf)
    r   = analyze_page(doc[page_num - 1])
    doc.close()

    print(f"\n{'Конструкція':<40} {'К-сть':>6} {'Од.':<6}")
    print("-" * 55)
    for prefix, count in sorted(r["counts"].items()):
        print(f"{prefix:<40} {count:>6} шт.")
    if r["col_color"] and r["col_count"]:
        print(f"{'Колони':<40} {r['col_count']:>6} шт.   [{r['col_color']}]")
    print(f"\nВсього: {sum(r['counts'].values()) + r['col_count']}")
    print(f"[debug] candidates: {json.dumps(r['candidates'], ensure_ascii=False)}")
    print(f"[debug] column color: {r['col_color']}")


if __name__ == "__main__":
    main()
