"""Usage: uv run python floor_plan_extract.py <pdf> <page_number>"""
import sys, base64, re
from collections import Counter
from dotenv import load_dotenv
load_dotenv()
import fitz
import instructor
from pydantic import BaseModel, Field

CODE_RE = re.compile(r'^[А-ЯҐЄІЇа-яґєії]{1,5}-\d{1,3}[А-ЯҐЄІЇа-яґєії]?$')


class Item(BaseModel):
    name: str
    quantity: int
    unit: str


class Plan(BaseModel):
    items: list[Item] = Field(description="Constructions counted directly from the sketch drawing only, not from tables")


def main():
    pdf, page = sys.argv[1], int(sys.argv[2])
    doc = fitz.open(pdf)
    p = doc[page - 1]
    pix = p.get_pixmap(matrix=fitz.Matrix(2, 2))
    img = base64.b64encode(pix.tobytes("png")).decode()

    # count labeled elements deterministically — no LLM needed for these
    label_counts = Counter()
    for w in p.get_text("words"):
        t = w[4].strip()
        if CODE_RE.match(t):
            prefix = t.rsplit("-", 1)[0]
            label_counts[prefix] += 1

    labeled_summary = "\n".join(f"  {k}: {v}" for k, v in sorted(label_counts.items()))
    doc.close()

    client = instructor.from_provider("openai/gpt-4o-mini")
    result = client.create(
        response_model=Plan,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Проаналізуй план поверху.\n\n"
                    f"Вже підраховані з тексту (точні дані — використовуй як є):\n{labeled_summary}\n\n"
                    "Додатково, дивлячись ТІЛЬКИ на графічний ескіз (не таблиці), підрахуй немарковані "
                    "конструкції: стіни, колони, сходові клітки, шахти — все що не має буквено-цифрового маркування. "
                    "Поверни всі елементи разом — і марковані з тексту, і немарковані з ескізу."
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}", "detail": "high"}},
            ],
        }],
    )

    print(f"\n{'Конструкція':<40} {'К-сть':>6} {'Од.':<6}")
    print("-" * 55)
    for item in result.items:
        print(f"{item.name:<40} {item.quantity:>6} {item.unit:<6}")
    print(f"\nВсього: {len(result.items)} позицій")


if __name__ == "__main__":
    main()
