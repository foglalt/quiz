import json
import re
from pathlib import Path

import pdfplumber
import pytesseract
from PIL import Image
from PyPDF2 import PdfReader


def clean_opt_text(text: str) -> str:
    text = re.sub(r"Helyes!?Helyes!?|Helyes válasz|Megadott válasz", "", text, flags=re.IGNORECASE)
    text = text.replace("Helyes válaszok", "")
    text = text.replace("okok", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .")


def parse_block(block: str) -> dict:
    lines = block.strip().split("\n")
    header = lines[0]
    body_lines = lines[1:]

    question_lines: list[str] = []
    options: list[tuple[str, bool]] = []
    current_opt: str | None = None
    current_correct = False
    started = False
    prev_blank = False
    force_options = False

    for line in body_lines:
        if "Kvízeredm" in line or "Kezdőlap" in line:
            break

        if "Helyes válaszok" in line:
            force_options = True
            if current_opt is not None:
                options.append((current_opt, current_correct))
            current_opt = None
            current_correct = False
            prev_blank = True
            continue

        stripped = line.rstrip("\n")
        if force_options and stripped:
            if current_opt is not None:
                options.append((current_opt, True))
            current_opt = stripped
            current_correct = True
            prev_blank = False
            started = True
            continue

        leading = len(line) - len(line.lstrip(" "))
        is_two_space = leading == 2
        is_correct = "Helyes" in line or force_options
        has_marker = is_correct or ("Megadott válasz" in line)

        if started and not prev_blank and current_opt and not is_two_space and is_correct:
            current_opt = (current_opt + " " + stripped).strip()
            current_correct = current_correct or is_correct
            prev_blank = stripped.strip() == ""
            continue

        opt_start = (
            is_two_space
            or (started and prev_blank and bool(stripped))
            or (not started and (is_two_space or has_marker))
        )

        if not started and opt_start:
            started = True
            current_opt = stripped
            current_correct = is_correct
        elif not started:
            question_lines.append(stripped)
        else:
            if opt_start:
                if current_opt is not None:
                    options.append((current_opt, current_correct))
                current_opt = stripped
                current_correct = is_correct
            else:
                if stripped:
                    current_opt = (current_opt + " " + stripped) if current_opt else stripped
                    if is_correct:
                        current_correct = True

        prev_blank = stripped.strip() == ""

    if current_opt is not None:
        options.append((current_opt, current_correct))

    qtext = "\n".join([q for q in question_lines if q]).strip()

    merged: dict[str, bool] = {}
    order: list[str] = []
    for opt, corr in options:
        clean = clean_opt_text(opt)
        if not clean:
            continue
        if clean not in merged:
            merged[clean] = corr
            order.append(clean)
        else:
            merged[clean] = merged[clean] or corr

    cleaned_opts = [{"text": t, "correct": merged[t]} for t in order]
    return {"header": header, "question": qtext, "options": cleaned_opts}


def parse_kviz12_ocr(pdf_path: Path) -> list[dict]:
    """OCR-alapú feldolgozás a kviz12.pdf-hez."""

    def ocr_text() -> str:
        texts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                img = page.to_image(resolution=250).original  # PIL Image
                text = pytesseract.image_to_string(img, lang="eng+hun")
                texts.append(text)
        return "\n\n".join(texts)

    def parse_blocks(text: str) -> list[dict]:
        parts = re.split(r"\n(?=\d+\. k)", text)
        questions = []
        for part in parts[1:]:
            lines = [l.strip() for l in part.split("\n") if l.strip()]
            lines = [
                l
                for l in lines
                if "Kviz-12" not in l
                and "module" not in l
                and not re.match(r"\d+ of \d+", l)
                and not re.match(r"\d{1,2}/\d{1,2}/\d{2}", l)
            ]
            if not lines:
                continue
            header = lines[0]
            rest = lines[1:]
            if not rest:
                continue

            idx_marker = next((i for i, l in enumerate(rest) if re.search(r"helyes", l, re.I)), len(rest))
            q_end = -1
            for i in range(min(idx_marker, len(rest))):
                if (
                    "?" in rest[i]
                    or "kód" in rest[i].lower()
                    or "kell" in rest[i].lower()
                    or "mit " in rest[i].lower()
                    or "melyik" in rest[i].lower()
                ):
                    q_end = i
            if q_end == -1:
                q_end = 0

            question_lines = rest[: q_end + 1]
            option_lines = rest[q_end + 1 :]

            options = []
            buf = ""
            buf_corr = False
            next_corr = False
            for line in option_lines:
                if re.fullmatch(r"(?i)helyes!?|helyes valasz|delyes valasz", line):
                    next_corr = True
                    continue

                if re.search(r"helyes", line, re.I):
                    clean_line = re.sub(r"(?i)helyes!?|helyes valasz|delyes valasz", "", line).strip(" .|")
                    if clean_line:
                        if buf:
                            options.append({"text": buf.strip(), "correct": buf_corr})
                        options.append({"text": clean_line, "correct": True})
                        buf, buf_corr, next_corr = "", False, False
                    continue

                if buf:
                    if (not buf.endswith((".", "?", "!"))) or line[:1].islower():
                        buf += " " + line
                        continue
                    else:
                        options.append({"text": buf.strip(), "correct": buf_corr})
                        buf = ""

                buf = line
                buf_corr = next_corr
                next_corr = False

            if buf:
                options.append({"text": buf.strip(), "correct": buf_corr})

            questions.append(
                {
                    "header": header,
                    "question": "\n".join(question_lines).strip(),
                    "options": options,
                }
            )
        return questions

    def fixups(qs: list[dict]) -> list[dict]:
        fixed = []
        for q in qs:
            # általános javítás: ha csak False van, adjuk hozzá a True opciót
            if len(q["options"]) == 1 and q["options"][0]["text"].lower() in ("false", "hamis"):
                q["options"].append({"text": "True", "correct": False})

            for opt in q["options"]:
                if re.search(r"helyes", opt["text"], re.I) or re.search(r"delyes", opt["text"], re.I):
                    opt["text"] = re.sub(r"(?i)helyes!?|helyes valasz|delyes valasz", "", opt["text"]).strip(" .|")
                    opt["correct"] = True

            # 16. kérdés speciális: iloc[1] -> második sor értékei
            if q["header"].startswith("16. kérdés"):
                q["question"] = "Mit ad vissza az alábbi kód?\ndf = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})\nprint(df.iloc[1])"
                q["options"] = [
                    {"text": "A második oszlop értékeit.", "correct": False},
                    {"text": "A sorindexet.", "correct": False},
                    {"text": "A második sor értékeit.", "correct": True},
                    {"text": "Hibát ad, mert hibás a szintaxis.", "correct": False},
                ]

            fixed.append(q)
        return fixed

    ocr_txt = ocr_text()
    return fixups(parse_blocks(ocr_txt))


def parse_pdf(path: Path) -> list[dict]:
    if path.name.lower().startswith("kviz12"):
        return parse_kviz12_ocr(path)

    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    blocks = re.split(r"(?=\d+ / \d+ pont \d+\. kérdés)", text)
    return [parse_block(b) for b in blocks[1:]]


def fix_missing_answers(entry: dict) -> dict:
    """Ad-hoc kiegészítések azokra a kérdésekre, ahol a PDF-ben nincs jelölt válasz."""
    if any(opt["correct"] for opt in entry["options"]):
        return entry

    qlower = entry["question"].lower()

    if "rekurzív  lambda" in qlower and "factor" in qlower:
        entry["options"] = [
            {"text": "factor = lambda a: 1 if a <= 1 else a * factor(a - 1)", "correct": True}
        ]
    elif "páratlan voltának" in qlower and "is_odd" in qlower:
        entry["options"] = [{"text": "is_odd = lambda a: a % 2 == 1", "correct": True}]
    elif "range (7, 10, -1)" in entry["question"]:
        entry["options"] = [
            {"text": "Error, mert nem lehet -1 lépésekkel eljutni 7-ből 10-be", "correct": True}
        ]
    elif "def a(**b)" in entry["question"]:
        entry["options"] = [
            {
                "text": "ár: 123000\n    darab: 2\n    Nincs fizetési mód megadva.",
                "correct": True,
            }
        ]
    elif "milyen feladatokra használtad eddig a pythont" in qlower:
        entry["options"] = [{"text": "Szabad szöveges válasz (reflexiós kérdés)", "correct": True}]
    elif not entry["options"]:
        entry["options"] = [{"text": "Szabad szöveges válasz", "correct": True}]

    return entry


def quiz_label(path: Path) -> str:
    match = re.search(r"Kvíz[- ]?(\d+)", path.stem)
    return f"kviz-{match.group(1)}" if match else path.stem.replace(" ", "-").lower()


def main() -> None:
    pdf_files = sorted(Path(".").glob("*.pdf"))
    questions: list[dict] = []

    for pdf in pdf_files:
        quiz_id = quiz_label(pdf)
        parsed = parse_pdf(pdf)
        for idx, q in enumerate(parsed, start=1):
            q = fix_missing_answers(q)
            entry = {
                "id": f"{quiz_id}-q{idx:02d}",
                "quiz": quiz_id,
                "question": q["question"],
                "options": q["options"],
            }
            questions.append(entry)

    Path("questions.json").write_text(
        json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(questions)} questions to questions.json")


if __name__ == "__main__":
    main()
