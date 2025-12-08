import json
import re
from pathlib import Path

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


def parse_pdf(path: Path) -> list[dict]:
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
    match = re.search(r"Kvíz[- ]?(\\d+)", path.stem)
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
