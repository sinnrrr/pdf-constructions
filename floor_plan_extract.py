"""Usage: uv run python floor_plan_extract.py <pdf> <page_number>"""
import sys, re, json, math
from collections import Counter, defaultdict
from dotenv import load_dotenv
load_dotenv()
import fitz
import instructor
from pydantic import BaseModel, Field

CODE_RE = re.compile(r'^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$')

# Area and shape filters
COL_MIN_AREA  = 100
COL_MAX_AREA  = 15_000
SHAFT_MIN_AREA = 15_000
SHAFT_MAX_AREA = 400_000
MAX_ASPECT     = 5.0
MIN_COUNT      = 5
MAX_COUNT      = 150


def _hex(color) -> str | None:
    """Convert fitz color (tuple of 0-1 floats) to #rrggbb, or None."""
    if color is None:
        return None
    if isinstance(color, (int, float)):
        v = int(round(color * 255))
        return f"#{v:02x}{v:02x}{v:02x}"
    if len(color) == 3:
        r, g, b = (int(round(c * 255)) for c in color)
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def extract_fill_candidates(page) -> list[dict]:
    """Return color statistics for candidate structural fill colors."""
    drawings = page.get_drawings()

    # Accumulate per fill-color: list of (area, aspect_ratio)
    by_color: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for d in drawings:
        fill = _hex(d.get("fill"))
        if fill is None or fill == "#ffffff":
            continue
        rect = d.get("rect")
        if rect is None:
            continue
        w = rect.width
        h = rect.height
        if w <= 0 or h <= 0:
            continue
        area = w * h
        aspect = max(w, h) / min(w, h)
        by_color[fill].append((area, aspect))

    candidates = []
    for color, shapes in by_color.items():
        if not shapes:
            continue
        avg_area   = sum(a for a, _ in shapes) / len(shapes)
        avg_aspect = sum(r for _, r in shapes) / len(shapes)
        count      = len(shapes)

        # Keep only colors that could be structural (columns or shafts)
        is_col_size   = COL_MIN_AREA   <= avg_area <= COL_MAX_AREA
        is_shaft_size = SHAFT_MIN_AREA <= avg_area <= SHAFT_MAX_AREA
        if not (is_col_size or is_shaft_size):
            continue
        if avg_aspect > MAX_ASPECT:
            continue
        if not (MIN_COUNT <= count <= MAX_COUNT):
            continue

        candidates.append({
            "color":      color,
            "count":      count,
            "avg_area":   round(avg_area, 1),
            "avg_aspect": round(avg_aspect, 2),
        })

    # Sort by count descending for readability
    candidates.sort(key=lambda x: -x["count"])
    return candidates


class ColorRoles(BaseModel):
    columns_color: str | None = Field(
        None,
        description="Hex color (#rrggbb) that represents structural columns/pylons, or null if unclear",
    )
    shafts_color: str | None = Field(
        None,
        description="Hex color (#rrggbb) that represents elevator shafts / staircase cores, or null if unclear",
    )


def identify_colors(client, candidates: list[dict]) -> ColorRoles:
    """One cheap text-only LLM call: which color is columns, which is shafts?"""
    if not candidates:
        return ColorRoles()

    payload = json.dumps(candidates, ensure_ascii=False, indent=2)
    prompt = (
        "You are analyzing fill-color statistics extracted from an architectural floor plan.\n"
        "Each entry has: color (hex), count (number of shapes), avg_area (pixels²), avg_aspect (max/min side ratio).\n\n"
        "Candidate colors:\n"
        f"{payload}\n\n"
        "Rules:\n"
        "- Structural columns/pylons are small, numerous, roughly square (area 100–15000, aspect < 3).\n"
        "- Elevator shafts / staircase cores are large rectangles (area > 15000, aspect < 4).\n"
        "- Columns are usually a mid-gray or dark color (they represent solid concrete/masonry).\n"
        "- Return the hex color string for each role, or null if you cannot determine it.\n"
        "- Only return colors from the list above."
    )

    return client.create(
        response_model=ColorRoles,
        messages=[{"role": "user", "content": prompt}],
    )


def count_by_color(drawings: list, color: str, min_area: float, max_area: float) -> int:
    """Filter drawings by fill color, cluster centroids, return cluster count.

    Includes all shapes ≥ 10 area (tiny markers are part of the same symbol).
    Radius is derived from large shapes only so adjacent columns aren't merged.
    """
    if not color:
        return 0

    centroids = []
    big_areas = []  # shapes in the requested size band — used for radius only
    for d in drawings:
        fill = _hex(d.get("fill"))
        if fill != color:
            continue
        rect = d.get("rect")
        if rect is None:
            continue
        w = rect.width
        h = rect.height
        if w <= 0 or h <= 0:
            continue
        area = w * h
        if area < 10:          # skip near-invisible artefacts
            continue
        cx = rect.x0 + w / 2
        cy = rect.y0 + h / 2
        centroids.append((cx, cy))
        if min_area <= area <= max_area:
            big_areas.append(area)

    if not centroids:
        return 0

    # ponytail: radius from big shapes only; tiny markers cluster into them automatically
    avg_big = sum(big_areas) / len(big_areas) if big_areas else (min_area + max_area) / 2
    radius  = math.sqrt(avg_big) * 0.5   # ~half column width — merges same-column paths, not neighbors

    clusters: list[tuple[float, float]] = []
    for cx, cy in sorted(centroids, key=lambda p: (p[0], p[1])):
        merged = False
        for j, (kx, ky) in enumerate(clusters):
            if math.hypot(cx - kx, cy - ky) <= radius:
                clusters[j] = ((kx + cx) / 2, (ky + cy) / 2)
                merged = True
                break
        if not merged:
            clusters.append((cx, cy))

    return len(clusters)


def main():
    pdf, page_num = sys.argv[1], int(sys.argv[2])
    doc = fitz.open(pdf)
    p   = doc[page_num - 1]

    # ── 1. Count labeled elements deterministically (unchanged) ──────────────
    label_counts: Counter = Counter()
    for w in p.get_text("words"):
        t = w[4].strip()
        if CODE_RE.match(t):
            prefix = t.rsplit("-", 1)[0]
            label_counts[prefix] += 1

    # ── 2. Extract fill-color candidates for structural elements ─────────────
    drawings   = p.get_drawings()
    candidates = extract_fill_candidates(p)
    doc.close()

    client = instructor.from_provider("openai/gpt-4o-mini")

    # ── 3. Cheap text-only LLM call: identify which color = columns / shafts ─
    roles = identify_colors(client, candidates)

    # ── 4. Count deterministically by identified colors ──────────────────────
    col_count   = count_by_color(drawings, roles.columns_color, COL_MIN_AREA,   COL_MAX_AREA)
    shaft_count = count_by_color(drawings, roles.shafts_color,  SHAFT_MIN_AREA, SHAFT_MAX_AREA)

    # ── 5. Print merged results ───────────────────────────────────────────────
    print(f"\n{'Конструкція':<40} {'К-сть':>6} {'Од.':<6}")
    print("-" * 55)

    for prefix, count in sorted(label_counts.items()):
        print(f"{prefix:<40} {count:>6} {'шт.':<6}")

    if roles.columns_color and col_count > 0:
        print(f"{'Колони':<40} {col_count:>6} {'шт.':<6}  [{roles.columns_color}]")
    elif roles.columns_color:
        print(f"{'Колони':<40} {'?':>6} {'шт.':<6}  [{roles.columns_color} — no shapes matched]")
    else:
        print(f"{'Колони':<40} {'?':>6} {'шт.':<6}  [колір не визначено]")

    if roles.shafts_color and shaft_count > 0:
        print(f"{'Шахти/сходові клітки':<40} {shaft_count:>6} {'шт.':<6}  [{roles.shafts_color}]")
    elif roles.shafts_color:
        pass  # 0 shafts is plausible, skip noisy line
    else:
        pass  # unknown, skip

    total = sum(label_counts.values()) + col_count + shaft_count
    print(f"\nВсього елементів: {total}")

    if candidates:
        print(f"\n[debug] fill candidates: {json.dumps(candidates, ensure_ascii=False)}")
    print(f"[debug] LLM identified → columns={roles.columns_color}, shafts={roles.shafts_color}")


if __name__ == "__main__":
    main()
