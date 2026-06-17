import ijson
import re
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

CODE_RE = re.compile(r'^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$')


def stream_pages(path: str):
    """Yield one page dict at a time without loading the full file."""
    with open(path, "rb") as f:
        for page in ijson.items(f, "pages.item"):
            yield page


def extract_page(p: dict):
    pi = p["index"] + 1
    spans, drawings = [], []

    for block in p["text_dict"]["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                bb = span["bbox"]
                spans.append((pi, t, bb[0], bb[1], bb[2], bb[3],
                               round(span["size"], 2), span["font"],
                               span.get("color"), bool(CODE_RE.match(t))))

    for d in p["drawings"]:
        r = d.get("rect") or [None, None, None, None]
        drawings.append((pi, d.get("type"), r[0], r[1], r[2], r[3],
                         str(d.get("color")), str(d.get("fill")),
                         d.get("width"), len(d.get("items", []))))

    page_row = (pi, round(p["width"]), round(p["height"]), p["rotation"],
                len(p["text_dict"]["blocks"]),
                sum(len(l["spans"]) for b in p["text_dict"]["blocks"] for l in b.get("lines", [])),
                len(spans), len(drawings), len(p["images"]))

    return page_row, spans, drawings


SPAN_COLS  = ["page","text","x0","y0","x1","y1","size","font","color","is_code"]
DRAW_COLS  = ["page","type","x0","y0","x1","y1","color","fill","width","item_count"]
PAGE_COLS  = ["page","width","height","rotation","blocks","spans","nonempty_spans","drawings","images"]


def analyze(json_path: str, prefix: str):
    print(f"\n{'='*60}")
    print(f"Analyzing {json_path} ...")

    page_rows, all_spans, all_drawings = [], [], []

    for i, page in enumerate(stream_pages(json_path)):
        if i % 10 == 0:
            print(f"  page {page['index']+1}...", flush=True)
        pr, spans, drawings = extract_page(page)
        page_rows.append(pr)
        all_spans.extend(spans)
        all_drawings.extend(drawings)

    pages_df    = pd.DataFrame(page_rows,    columns=PAGE_COLS)
    spans_df    = pd.DataFrame(all_spans,    columns=SPAN_COLS)
    drawings_df = pd.DataFrame(all_drawings, columns=DRAW_COLS)

    pages_df.to_parquet(f"{prefix}_pages.parquet",    index=False)
    spans_df.to_parquet(f"{prefix}_spans.parquet",    index=False)
    drawings_df.to_parquet(f"{prefix}_drawings.parquet", index=False)
    print(f"  Saved parquet files.")

    # ── Page summary ──────────────────────────────────────────────────────────
    print("\n--- Page summary ---")
    print(pages_df.to_string(index=False))

    # ── Spans ─────────────────────────────────────────────────────────────────
    codes = spans_df[spans_df["is_code"]]
    print(f"\n--- Spans ---")
    print(f"Total spans: {len(spans_df):,}  |  Code spans: {len(codes):,}  |  Unique codes: {codes['text'].nunique()}")

    print("\nTop codes (all pages):")
    print(codes["text"].value_counts().head(20).to_string())

    print("\nCode spans per page:")
    print(codes.groupby("page")["text"].count().sort_values(ascending=False).head(20).to_string())

    # ── Fonts ─────────────────────────────────────────────────────────────────
    print("\nTop fonts:")
    print(spans_df["font"].value_counts().head(10).to_string())

    print("\nTop font sizes:")
    print(spans_df["size"].value_counts().head(10).to_string())

    # ── Drawings ──────────────────────────────────────────────────────────────
    print(f"\n--- Drawings ---")
    print(f"Total paths: {len(drawings_df):,}")
    print("\nDrawing types:")
    print(drawings_df["type"].value_counts().to_string())
    print("\nTop fill colors:")
    print(drawings_df["fill"].value_counts().head(10).to_string())


if __name__ == "__main__":
    analyze("kardamon_dump.json", "kardamon")
    analyze("lviv_dump.json", "lviv")
