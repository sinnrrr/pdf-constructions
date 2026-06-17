import pymupdf, json, sys

def dump_pdf(path, out_path):
    doc = pymupdf.open(path)
    data = {
        "metadata": doc.metadata,
        "page_count": len(doc),
        "layers": doc.get_layers(),
        "pages": []
    }

    for i, page in enumerate(doc):
        data["pages"].append({
            "index": i,
            "width": page.rect.width,
            "height": page.rect.height,
            "rotation": page.rotation,
            "text_dict": page.get_text("dict"),
            "images": page.get_images(full=True),
            "drawings": page.get_drawings(),
            "links": page.get_links(),
            "annots": [a.info for a in page.annots()],
        })

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"Done: {out_path}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python dump.py <input.pdf> <output.json>")
        sys.exit(1)
    dump_pdf(sys.argv[1], sys.argv[2])
