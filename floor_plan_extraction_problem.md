# Floor Plan Construction Element Extraction — Problem Description

## What This Is

An automation task: given an architectural PDF, count all construction elements per floor and output a structured table. The PDFs are working architectural documentation (робоча документація) produced by Ukrainian design bureaus for residential/hotel/mixed-use buildings.

The original request (verbatim, Ukrainian):
> "проаналізуй ескіз плану 9 поверху та виведи в таблицю всі конструкції та їх кількості, для аналізу візьми тільки ескіз поверху і не бери до уваги інформацію в таблицях"
> 
> "analyze the 9th floor plan sketch and output all constructions and their quantities in a table — take only the floor sketch, do not consider the information in the tables"

The tables are explicitly excluded because **they contain incorrect/outdated data**. The sketch is the source of truth.

---

## The Two PDFs Examined

### PDF 1 — Кардамон hotel, Ivano-Frankivsk region
- File: `Кардамон_АР_РП_з_реальними_відмітками_2.pdf`
- Size: 50.5 MB, 94 pages
- Project: 14-floor hotel, new construction
- CAD software: likely AutoCAD/Revit (pure vector export)
- Orientation: **landscape** (4212×1684 pts per page)
- Floor plan pages: 13–28 (план опорядження per floor)
- Element codes: `Дв-*` (двері/doors), `Вк-*` (вікна/windows)
- Tables on floor plan pages: **Специфікація заповнення прорізів** — lists each Дв/Вк code once with (wrong) quantity
- Notable anomaly: page 15 (2nd floor) has 43 embedded raster images instead of vector text — labels not extractable as text. The floor is a restaurant/terrace concept plan ("A LA CARTE", "F&B"), likely generated differently in CAD.

### PDF 2 — Євротек девелопмент, Lviv
- File: `2025-06-13_KNO120_AVR_AR_RD_1.1,2.pdf`
- Size: 34.2 MB, 82 pages
- Project: multi-functional complex, 2 residential buildings + underground parking
- CAD software: likely ArchiCAD (different title block format, different export style)
- Orientation: **portrait** (1684×2384 pts per page)
- Floor plan pages: p04–p19 (план поверху), p20–p44 (план мурування per floor per building)
- Element codes: `Д-*`, `ПД-*`, `ПД-2л` (mirrored) for doors; `В-*` for windows; also `Б-*` (балконні блоки), `ВШ-*` (вентиляційні шахти), `ФС-*` (склопрозорі фасадні системи), `СП-*` (скляні перегородки), `ПВр-*` (ворота)
- Tables on floor plan pages: **Експлікація приміщень** — room names and areas only, does NOT contain element codes

---

## What a Floor Plan Page Looks Like

Each floor plan page contains two distinct regions:

1. **The sketch** (~60–80% of page area): a CAD floor plan drawing showing:
   - Rooms with colored fills (beige = living, blue = bathroom, etc.)
   - Walls as thick lines
   - Structural axes (numbered/lettered grid)
   - Element symbols: door arcs, window lines, column rectangles
   - **Labels placed directly next to each element instance**: `Дв-20`, `В-1`, `Б-5`, etc. Each physical element gets its own label placed beside it in the drawing.
   - Dimensions, room numbers, area values

2. **Tables** (~20–40% of page, in margins): depending on project, these can be:
   - Специфікація заповнення прорізів (element code + quantity + dimensions) — **codes appear here but counts are WRONG**
   - Експлікація приміщень (room schedule: room name + area) — no element codes
   - Title block (project info, sheet number, signatures)
   - Legend / умовні позначення (color/line type key)

---

## The Core Counting Logic

In a CAD floor plan drawing, every physical element of a given type gets the same code label placed beside it individually:
- If `Дв-20` appears 26 times in the sketch → there are 26 doors of type Дв-20
- If `В-1` appears 18 times in the sketch → there are 18 windows of type В-1

The specification table in the margin lists each code once as a row label with a pre-calculated quantity column. That quantity is wrong (outdated/incorrect per the client). The count from the sketch labels is the ground truth.

---

## What Has Been Tried

### Approach 1: Hardcoded spatial boundary (FAILED — not general)
Extract all text via PyMuPDF, filter to x < 2600 (sketch region), count code occurrences.
- **Worked** for PDF 1 (landscape, tables on right at x ≈ 2696)
- **Does not work** for PDF 2 (portrait orientation, different table position)
- **Fundamentally brittle**: every new PDF has a different page size and table layout

### Approach 2: PyMuPDF `find_tables()` (FAILED — wrong abstraction)
Use PyMuPDF's built-in table detector to auto-detect and exclude table bounding boxes.
- `find_tables()` detected the **entire floor plan drawing area** as "Table 0" (because the floor plan's structural grid of lines looks like a table to the algorithm)
- PDF 1 floor9: Table 0 = `[0, 14, 4198, 1675]` — the whole page
- PDF 2 page8: Table 0 = `[1, 14, 1670, 2370]` — again the whole page
- Unusable

### Approach 3: Text frequency / statistical (PARTIAL — fails edge cases)
Element codes appearing 2+ times are definitely sketch instances (tables only list each code once per row).
- Codes appearing exactly once are ambiguous: could be 1 real element OR a table-only reference
- Practically, most codes appear many times, so error is small
- But not reliable enough for professional use

### Approach 4: Spatial isolation heuristic (TOO BRITTLE)
Count neighboring words around each code occurrence — isolated code = sketch, surrounded code = table row.
- Still layout-dependent, requires tuning proximity radius
- Fragile against different line spacings and font sizes across projects

---

## What Stays Constant Across All PDFs

Despite everything changing between projects, two things are universal:

1. **General code pattern**: All projects use `{Cyrillic prefix}-{number}` format.  
   Regex: `^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$`  
   This correctly catches: `Дв-20`, `Вк-7`, `Д-11`, `ПД-2л`, `В-1`, `Б-5`, `ФС-18`, `ВШ-4`, `СП-3` — any project.

2. **Visual structure**: Every floor plan sketch is a recognizable 2D architectural drawing with colored filled rooms, black/dark walls, labeled element symbols. Tables are visually distinct from the sketch — they look like tables.

---

## Why Vision Models Are the Right Abstraction

The spatial filtering approaches are fighting the wrong battle. The problem is fundamentally **visual comprehension**, not text parsing:

- A human looks at the floor plan sketch and counts door arcs labeled `Д-1`
- A human ignores the table in the corner because it visually looks like a table
- A human doesn't need to know the x-coordinate of the table boundary

A vision model (Claude, GPT-4o, Qwen2.5-VL) can do the same:
- Render the PDF page to a high-res image
- Visually distinguish sketch from tables
- Count label occurrences within the sketch area
- Return structured output

The key advantage: the model understands **semantic visual regions** (this is a floor plan, that is a table), not pixel coordinates. This is layout-agnostic by design.

---

## Practical Constraints and Tradeoffs

| Factor | Vision LLM | PyMuPDF text extraction |
|---|---|---|
| Layout agnostic | ✅ Yes | ❌ No — brittle |
| Cost | ~$0.01–0.05 per page | $0 |
| Accuracy on labeled elements | ~85–95% | ~95–100% (when layout is correct) |
| Accuracy on sketch-only elements | ~70–85% | N/A |
| Works on rasterized pages (like PDF1 p15) | ✅ Yes | ❌ No |
| Works for any element code convention | ✅ Yes | Needs regex tuning |
| Sensitive to image resolution | Yes (need ≥150 DPI) | No |
| Requires API key / internet | Yes (or local model) | No |
| Latency per page | 3–15s | <100ms |

---

## Open Questions

1. **Which vision model performs best on Ukrainian architectural CAD drawings?**  
   Candidates: Claude Sonnet/Opus (strong document understanding), GPT-4o (strong visual), Qwen2.5-VL-7B (strong DocVQA, local/free).

2. **What is the right output schema?** Per floor: list of (code, count) pairs? Or a wider matrix across all floors?

3. **How to handle the "ignore tables" instruction visually?** A good prompt should instruct the model to count only symbols it sees drawn in the floor plan sketch, not numbers listed in any table in the margins.

4. **Batch processing**: The full pipeline needs to identify which pages are floor plans (vs facades, sections, specifications) and extract the floor name from each page.

5. **Hybrid approach**: Use PyMuPDF to render + crop to sketch region (when determinable), then pass to vision model. This reduces context noise and improves counting accuracy.

6. **What element types to count?** Currently scoped to Дв+Вк (PDF 1) but a general solution should count all element codes present, grouped by type (doors, windows, facades, etc.). The user confirmed: for now Дв and Вк only — but the system should be general.

---

## Recommended Next Step

Test a vision model (Claude vision, already available in this session) directly on a rendered floor plan page from each PDF:
1. Render page to high-res PNG via PyMuPDF
2. Pass to vision model with a structured prompt: *"Count all element code labels visible in the floor plan sketch. Do not count values from tables. Return JSON: [{code, count}]"*
3. Measure accuracy against ground truth (known counts from PDF 1 text layer)
4. Assess whether vision alone is sufficient or needs hybrid text+vision pipeline
