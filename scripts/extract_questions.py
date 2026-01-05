import argparse
import json
import re
from pathlib import Path


PLACEHOLDER_EXPLANATION = "Magyarázat hamarosan."


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

    import pdfplumber  # optional dependency (only for OCR mode)
    import pytesseract  # optional dependency (only for OCR mode)

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
    if "beugro" in path.stem.lower() or "telekom" in path.stem.lower():
        return parse_beugro_telekom(path)
    if path.name.lower().startswith("kviz12"):
        return parse_kviz12_ocr(path)

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        from PyPDF2 import PdfReader  # type: ignore

    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    blocks = re.split(r"(?=\d+ / \d+ pont \d+\. kérdés)", text)
    return [parse_block(b) for b in blocks[1:]]


def _normalize_lines(text: str) -> list[str]:
    raw_lines = [l.rstrip() for l in text.splitlines()]
    lines: list[str] = []
    for line in raw_lines:
        if not line.strip():
            continue
        # collapse excessive whitespace but keep bullets
        line = re.sub(r"\s+", " ", line).strip()
        lines.append(line)

    # join broken words like "vár" + "akozik" (OCR/text-extraction line wraps)
    joined: list[str] = []
    for line in lines:
        if not joined:
            joined.append(line)
            continue

        prev = joined[-1]
        # If previous ends with a lowercase letter and current begins with lowercase,
        # and current is not a bullet and not a new question number, join without space.
        if (
            re.search(r"[a-záéíóöőúüű]$", prev)
            and re.match(r"^[a-záéíóöőúüű]", line)
            and not line.startswith("•")
            and not re.match(r"^\d+\.", line)
        ):
            joined[-1] = prev + line
        else:
            joined.append(line)
    return joined


def parse_beugro_telekom(pdf_path: Path) -> list[dict]:
    """Telekommunikációs beugró kvízkérdések PDF feldolgozása.

    A dokumentum sokszor tartalmazza a helyes megoldást sima szövegként az opciók után.
    Amikor nem szerepel megoldás a szövegben, a kérdéshez hozzáadunk egy jelző opciót.
    """

    import pdfplumber  # optional dependency (used for this PDF's extraction)

    HIGHLIGHT_GREEN = (0.0, 1.0, 0.0)
    GAP_THRESHOLD = 25.0

    def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)

    def clean_text(s: str) -> str:
        s = s.replace("\n", "")
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    def segment_row(chars: list[dict]) -> list[list[dict]]:
        # Split a single y-row into segments when there's a big x gap (prevents merging columns).
        if not chars:
            return []
        chars = sorted(chars, key=lambda c: float(c["x0"]))
        segs: list[list[dict]] = [[chars[0]]]
        for ch in chars[1:]:
            prev = segs[-1][-1]
            gap = float(ch["x0"]) - float(prev["x1"])
            if gap > GAP_THRESHOLD:
                segs.append([ch])
            else:
                segs[-1].append(ch)
        return segs

    def line_objects_for_page(page, page_index: int) -> list[dict]:
        rows: dict[float, list[dict]] = {}
        for ch in page.chars:
            t = ch.get("text", "")
            if not t or t == "\n":
                continue
            top = round(float(ch["top"]), 1)
            rows.setdefault(top, []).append(ch)

        rects: list[tuple[float, float, float, float]] = []
        for r in page.rects:
            if r.get("non_stroking_color") == HIGHLIGHT_GREEN:
                rects.append((float(r["x0"]), float(r["top"]), float(r["x1"]), float(r["bottom"])))

        out: list[dict] = []
        for top in sorted(rows.keys()):
            for seg in segment_row(rows[top]):
                text = clean_text("".join(c["text"] for c in seg))
                if not text:
                    continue
                x0 = min(float(c["x0"]) for c in seg)
                x1 = max(float(c["x1"]) for c in seg)
                y0 = min(float(c["top"]) for c in seg)
                y1 = max(float(c["bottom"]) for c in seg)
                bbox = (x0, y0, x1, y1)
                highlighted = any(overlaps(bbox, rr) for rr in rects) if rects else False
                out.append({"page": page_index, "text": text, "bbox": bbox, "highlight": highlighted})
        return out

    doc_lines: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages):
            doc_lines.extend(line_objects_for_page(page, idx))

    # Merge bullet-only lines: PDFs often store "•" on its own line.
    merged: list[dict] = []
    i = 0
    while i < len(doc_lines):
        cur = doc_lines[i]
        if cur["text"] == "•" and i + 1 < len(doc_lines):
            nxt = doc_lines[i + 1]
            # merge only if it's on the same page and next isn't a new question header or another bullet
            if nxt["page"] == cur["page"] and nxt["text"] != "•" and not re.match(r"^\d+\.", nxt["text"]):
                x0 = min(cur["bbox"][0], nxt["bbox"][0])
                y0 = min(cur["bbox"][1], nxt["bbox"][1])
                x1 = max(cur["bbox"][2], nxt["bbox"][2])
                y1 = max(cur["bbox"][3], nxt["bbox"][3])
                merged_bbox = (x0, y0, x1, y1)
                merged.append(
                    {
                        "page": cur["page"],
                        "text": f"• {nxt['text']}".strip(),
                        "bbox": merged_bbox,
                        "highlight": bool(cur["highlight"] or nxt["highlight"]),
                    }
                )
                i += 2
                continue
        merged.append(cur)
        i += 1

    # Now parse using the merged line texts.
    lines = _normalize_lines("\n".join(l["text"] for l in merged))

    # Group into question blocks based on real question headers at line start: "<num>. "
    # Build blocks from merged line objects (so we preserve highlight flags for options)
    blocks: list[tuple[str, list[dict]]] = []
    current_num: str | None = None
    current_block: list[dict] = []

    for obj in merged:
        line = obj["text"]
        m = re.match(r"^(\d+)\.\s*(.*)$", line)
        if m:
            if current_num is not None:
                blocks.append((current_num, current_block))
            current_num = m.group(1)
            rest = m.group(2).strip()
            current_block = [{**obj, "text": rest} if rest else obj]
        elif current_num is not None:
            current_block.append(obj)

    if current_num is not None:
        blocks.append((current_num, current_block))

    questions: list[dict] = []
    for num, body_objs in blocks:
        body_objs = [o for o in body_objs if o.get("text", "").strip()]
        if not body_objs:
            continue

        question_lines: list[str] = []
        option_lines: list[str] = []
        option_correct_by_highlight: list[bool] = []
        answer_lines: list[str] = []

        in_options = False
        question_ended = False

        for obj in body_objs:
            line = obj["text"].strip()
            if line.startswith("•"):
                in_options = True
                option_lines.append(line.lstrip("•").strip())
                option_correct_by_highlight.append(bool(obj.get("highlight")))
                continue

            if in_options:
                answer_lines.append(line)
                continue

            if question_ended:
                answer_lines.append(line)
                continue

            question_lines.append(line)
            if "?" in line or line.endswith("!"):
                question_ended = True

        question_text = "\n".join(question_lines).strip()
        answer_text = " ".join(answer_lines).strip() if answer_lines else ""

        # Some rows use " / " to repeat phrasing; keep it as-is.

        # Build options in the app's expected format.
        options: list[dict] = []
        explanation = PLACEHOLDER_EXPLANATION

        tf_answer = None
        if answer_text:
            if re.match(r"^igaz\b", answer_text, flags=re.I):
                tf_answer = "Igaz"
            elif re.match(r"^hamis\b", answer_text, flags=re.I):
                tf_answer = "Hamis"

        if tf_answer is not None or re.match(r"^igaz vagy hamis\?", question_text, flags=re.I):
            correct_is_igaz = tf_answer == "Igaz"
            options = [
                {"text": "Igaz", "correct": bool(correct_is_igaz)},
                {"text": "Hamis", "correct": bool(tf_answer == "Hamis")},
            ]
            if tf_answer is None:
                explanation = "A PDF-ben ehhez a kérdéshez nem szerepel jelölt megoldás."
                # Ensure at least one correct option so the UI can show a solution.
                options[0]["correct"] = True
        elif option_lines:
            # Create MC options; try to match an explicit answer line to one of the options.
            lowered_answer = answer_text.lower() if answer_text else ""
            matched = False
            for idx, opt in enumerate(option_lines):
                is_correct = False
                if idx < len(option_correct_by_highlight) and option_correct_by_highlight[idx]:
                    is_correct = True
                    matched = True
                if lowered_answer:
                    # Match either full equality or contained (common for short answers)
                    o = opt.strip().lower()
                    if o == lowered_answer.strip() or (o and o in lowered_answer) or (
                        lowered_answer and lowered_answer in o
                    ):
                        is_correct = True
                        matched = True
                options.append({"text": opt, "correct": is_correct})

            if not matched:
                if answer_text:
                    options.append({"text": answer_text, "correct": True})
                else:
                    options.append({"text": "A PDF nem tartalmazza a megoldást.", "correct": True})
                    explanation = "A PDF-ben ehhez a kérdéshez nem szerepel jelölt megoldás."
        else:
            # No explicit options -> treat as a short-answer flashcard.
            if answer_text:
                options = [{"text": answer_text, "correct": True}]
            else:
                options = [{"text": "Szabad szöveges válasz", "correct": True}]
                explanation = "A PDF-ben ehhez a kérdéshez nem szerepel megoldás."

        questions.append(
            {
                "header": f"{num}.",
                "question": question_text,
                "options": options,
                "explanation": explanation,
            }
        )

    return questions


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


def collect_pdfs(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        return sorted(input_path.glob("*.pdf"))
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    raise FileNotFoundError(f"Input not found or not a PDF/dir: {input_path}")


def build_questions(pdf_files: list[Path]) -> list[dict]:
    questions: list[dict] = []
    for pdf in pdf_files:
        quiz_id = quiz_label(pdf)
        parsed = parse_pdf(pdf)
        for idx, q in enumerate(parsed, start=1):
            q = fix_missing_answers(q)
            entry = {
                "id": f"{quiz_id}-q{idx:02d}",
                "question": q["question"],
                "options": q["options"],
                "explanation": PLACEHOLDER_EXPLANATION,
            }
            questions.append(entry)
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract quiz questions from PDF(s) into JSON.")
    parser.add_argument(
        "--input",
        "-i",
        default=".",
        help="Input PDF file or directory containing PDFs (default: current directory).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="questions.json",
        help="Output JSON path (default: questions.json).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    pdf_files = collect_pdfs(input_path)
    questions = build_questions(pdf_files)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(questions)} questions to {output_path}")


if __name__ == "__main__":
    main()
