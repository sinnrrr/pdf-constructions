import io
import fitz
import streamlit as st
import pandas as pd
from PIL import Image, ImageDraw
from streamlit_image_select import image_select
from floor_plan_extract import analyze_page

st.set_page_config(page_title="Аналіз плану поверху", page_icon="📐", layout="wide")

# ── cached helpers ────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def get_thumbnails(pdf_bytes: bytes) -> list[Image.Image]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    thumbs = [Image.open(io.BytesIO(doc[i].get_pixmap(dpi=50).tobytes("png")))
              for i in range(len(doc))]
    doc.close()
    return thumbs

# ── annotation ────────────────────────────────────────────────────────────────

ANNO_DPI      = 150       # 300 DPI is too large to display well in Streamlit; 150 stays sharp
_MAX_ANNO_PX  = 4_000_000 # cap rendered area (~4MP) so A0/A1 pages can't OOM the 1GB tier
_COLORS  = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336", "#00BCD4",
            "#795548", "#607D8B"]

# Marker radii in PDF points so they scale with the image; labels are ~15–18 pts wide
_R_LABEL_PTS = 15
_R_COL_PTS   = 20

def annotate(pdf_bytes: bytes, idx: int, result: dict) -> Image.Image:
    all_cx, all_cy = [], []
    for positions in result["positions"].values():
        for x0, y0, x1, y1 in positions:
            all_cx.append((x0 + x1) / 2)
            all_cy.append((y0 + y1) / 2)
    for cx, cy in result["col_points"]:
        all_cx.append(cx); all_cy.append(cy)

    doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[idx]

    if all_cx:
        pad_pts = 200  # ~70mm at 1:100 scale — one room of context around the detections
        clip = fitz.Rect(
            max(0,                min(all_cx) - pad_pts),
            max(0,                min(all_cy) - pad_pts),
            min(page.rect.width,  max(all_cx) + pad_pts),
            min(page.rect.height, max(all_cy) + pad_pts),
        )
        region = clip
        ox, oy = clip.x0, clip.y0
    else:
        clip   = None
        region = page.rect
        ox, oy = 0, 0

    # Cap render DPI so the pixmap area stays under _MAX_ANNO_PX — an A0 page at a
    # fixed 150 DPI is ~35MP and would blow past the 1GB tier through the pixmap +
    # PIL RGB + RGBA copies. Downscaling here bounds peak RAM to a few MB.
    dpi    = ANNO_DPI
    px_est = (region.width / 72 * dpi) * (region.height / 72 * dpi)
    if px_est > _MAX_ANNO_PX:
        dpi = max(36, int(dpi * (_MAX_ANNO_PX / px_est) ** 0.5))

    pix = page.get_pixmap(dpi=dpi, clip=clip)
    doc.close()
    img  = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    pix  = None  # drop the pixmap buffer before allocating the RGBA copy
    img  = img.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    s    = dpi / 72  # PDF pts → pixels
    r_l  = _R_LABEL_PTS * s
    r_c  = _R_COL_PTS   * s
    lw   = max(2, round(s))

    for i, prefix in enumerate(sorted(result["positions"])):
        color = _COLORS[i % len(_COLORS)]
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        for x0, y0, x1, y1 in result["positions"][prefix]:
            cx = ((x0 + x1) / 2 - ox) * s
            cy = ((y0 + y1) / 2 - oy) * s
            draw.ellipse([cx - r_l, cy - r_l, cx + r_l, cy + r_l],
                         fill=(r, g, b, 200), outline=(255, 255, 255, 255), width=lw)

    for cx, cy in result["col_points"]:
        px = (cx - ox) * s
        py = (cy - oy) * s
        draw.ellipse([px - r_c, py - r_c, px + r_c, py + r_c],
                     fill=(229, 57, 53, 200), outline=(255, 255, 255, 255), width=lw)

    return img.convert("RGB")

def legend_html(prefixes: list[str], has_cols: bool) -> str:
    items = [f'<span style="color:{_COLORS[i % len(_COLORS)]}">⬤</span> {p}'
             for i, p in enumerate(sorted(prefixes))]
    if has_cols:
        items.append('<span style="color:#E53935">○</span> Колони')
    return "  &nbsp;&nbsp;".join(items)

# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    uploaded = st.file_uploader("Завантажте PDF файл", type="pdf", label_visibility="collapsed")

    if uploaded:
        chosen_page   = st.session_state.get("chosen_page")
        sidebar_thumb = st.session_state.get("sidebar_thumb")

        if sidebar_thumb:
            st.image(sidebar_thumb, caption=f"стор. {chosen_page + 1}", width='stretch')
        else:
            st.caption("Клікніть на сторінку →")

        result = (st.session_state.get("results") or {}).get(chosen_page)
        if result:
            counts    = result["counts"]
            col_count = result["col_count"]
            total     = sum(counts.values()) + col_count
            num_types = len(counts) + (1 if col_count else 0)

            st.divider()
            m1, m2 = st.columns(2)
            m1.metric("Всього", total)
            m2.metric("Типів", num_types)

            rows = [{"Конструкція": k, "К-сть": v} for k, v in sorted(counts.items())]
            if col_count:
                rows.append({"Конструкція": "Колони", "К-сть": col_count})

            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, width='stretch',
                         column_config={"К-сть": st.column_config.NumberColumn("К-сть", format="%d")})

            buf = io.BytesIO()
            df.to_excel(buf, index=False, sheet_name="Конструкції")
            buf.seek(0)
            st.download_button(
                "⬇ Завантажити Excel",
                data=buf,
                file_name=f"{st.session_state.get('pdf_name', 'план')}_стор{chosen_page + 1}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,  # download_button doesn't support width= yet
            )

# ── main area ─────────────────────────────────────────────────────────────────

if not uploaded:
    st.info("Завантажте PDF файл з планом поверху щоб почати")
    st.stop()

pdf_bytes = uploaded.read()

with st.spinner("Готую сторінки…"):
    thumbs = get_thumbnails(pdf_bytes)

# seed chosen_page=0 to match image_select's default so it doesn't auto-fire on first load
if "chosen_page" not in st.session_state:
    st.session_state["chosen_page"] = 0
else:
    st.session_state["sidebar_thumb"] = thumbs[st.session_state["chosen_page"]]

is_analyzing = st.session_state.get("is_analyzing", False)
has_results  = "results" in st.session_state
gen          = st.session_state.get("analysis_gen", 0)

chosen = None  # image_select doesn't render while the expander is collapsed
with st.expander("Сторінки PDF", expanded=not (has_results or is_analyzing), key=f"pages_{gen}"):
    chosen = image_select(
        label="Клікніть на сторінку для аналізу",
        images=thumbs,
        captions=[f"стор. {i + 1}" for i in range(len(thumbs))],
        use_container_width=False,  # image_select doesn't support width= yet
        return_value="index",
    )

# phase 1: new selection → collapse expander immediately, mark as analyzing
if not is_analyzing and chosen is not None and chosen != st.session_state["chosen_page"]:
    st.session_state["chosen_page"]   = chosen
    st.session_state["sidebar_thumb"] = thumbs[chosen]
    st.session_state["is_analyzing"]  = True
    st.session_state["analysis_gen"]  = gen + 1
    st.rerun()

# phase 2: expander collapsed, now do the work
if is_analyzing:
    idx = st.session_state["chosen_page"]
    with st.spinner("Аналізую…"):
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        st.session_state["results"]  = {idx: analyze_page(doc[idx])}
        st.session_state["pdf_name"] = uploaded.name
        doc.close()
    st.session_state["is_analyzing"] = False
    st.rerun()

# ── annotated image ───────────────────────────────────────────────────────────

chosen_page = st.session_state["chosen_page"]
result      = (st.session_state.get("results") or {}).get(chosen_page)

if result:
    with st.expander("Показати що знайдено на кресленні", expanded=True):
        if result["positions"] or result["col_points"]:
            st.markdown(
                legend_html(list(result["positions"].keys()), bool(result["col_points"])),
                unsafe_allow_html=True,
            )
            st.image(annotate(pdf_bytes, chosen_page, result), width='stretch')
        else:
            st.info("Елементи не знайдено на цій сторінці")
