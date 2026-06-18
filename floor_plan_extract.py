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


def extract_col_candidates(page) -> list[dict]:
    by_color: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for d in page.get_drawings():
        fill = _hex(d.get("fill"))
        if fill is None or fill == "#ffffff":
            continue
        rect = d.get("rect")
        if rect is None:
            continue
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            continue
        by_color[fill].append((w * h, max(w, h) / min(w, h)))

    candidates = []
    for color, shapes in by_color.items():
        avg_area   = sum(a for a, _ in shapes) / len(shapes)
        avg_aspect = sum(r for _, r in shapes) / len(shapes)
        count      = len(shapes)
        if (COL_MIN_AREA <= avg_area <= COL_MAX_AREA
                and avg_aspect <= MAX_ASPECT
                and COL_MIN_COUNT <= count <= COL_MAX_COUNT):
            candidates.append({"color": color, "count": count,
                                "avg_area": round(avg_area, 1),
                                "avg_aspect": round(avg_aspect, 2)})
    candidates.sort(key=lambda x: -x["count"])
    return candidates


def count_columns(drawings: list, color: str) -> int:
    if not color:
        return 0
    centroids, big_areas = [], []
    for d in drawings:
        if _hex(d.get("fill")) != color:
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
        centroids.append((rect.x0 + w / 2, rect.y0 + h / 2))
        if COL_MIN_AREA <= area <= COL_MAX_AREA:
            big_areas.append(area)

    if not centroids:
        return 0

    avg_big = sum(big_areas) / len(big_areas) if big_areas else COL_MAX_AREA
    radius  = math.sqrt(avg_big) * 0.5

    clusters: list[tuple[float, float]] = []
    for cx, cy in sorted(centroids):
        for j, (kx, ky) in enumerate(clusters):
            if math.hypot(cx - kx, cy - ky) <= radius:
                clusters[j] = ((kx + cx) / 2, (ky + cy) / 2)
                break
        else:
            clusters.append((cx, cy))
    return len(clusters)


def _is_real_label(x0: float, y0: float,
                   decimals: list, calcs: list, has_calcs: bool) -> bool:
    """Return True if a filtered-prefix label at (x0,y0) looks like a real element."""
    if has_calcs:
        return bool(calcs) and min(math.hypot(cx - x0, cy - y0) for cx, cy in calcs) <= 115
    return any(v <= 2.5 for dx, dy, v in decimals if abs(dx - x0) < 80 and abs(dy - y0) < 80)


def main():
    pdf, page_num = sys.argv[1], int(sys.argv[2])
    doc = fitz.open(pdf)
    p   = doc[page_num - 1]

    words    = p.get_text("words")
    decimals = [(w[0], w[1], float(w[4].strip().replace(',', '.')))
                for w in words if DECIMAL_RE.match(w[4].strip())]
    calcs    = [(w[0], w[1]) for w in words if CALC_RE.match(w[4].strip())]
    has_calcs = bool(calcs)

    label_counts: Counter = Counter()
    for w in words:
        t = w[4].strip()
        if not CODE_RE.match(t):
            continue
        prefix = t.rsplit("-", 1)[0]
        if prefix in _FILTERED_PREFIXES:
            if not _is_real_label(w[0], w[1], decimals, calcs, has_calcs):
                continue
        label_counts[prefix] += 1

    drawings   = p.get_drawings()
    candidates = extract_col_candidates(p)
    doc.close()

    col_color = candidates[0]["color"] if candidates else None
    col_count = count_columns(drawings, col_color)

    print(f"\n{'Конструкція':<40} {'К-сть':>6} {'Од.':<6}")
    print("-" * 55)
    for prefix, count in sorted(label_counts.items()):
        print(f"{prefix:<40} {count:>6} шт.")
    if col_color and col_count:
        print(f"{'Колони':<40} {col_count:>6} шт.   [{col_color}]")
    print(f"\nВсього: {sum(label_counts.values()) + col_count}")
    print(f"[debug] candidates: {json.dumps(candidates, ensure_ascii=False)}")
    print(f"[debug] column color: {col_color}")


if __name__ == "__main__":
    main()
