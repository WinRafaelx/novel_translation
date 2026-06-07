import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_INPUT_DIR = "mount_hua_chapters"
DEFAULT_OUTPUT_DIR = "mount_hua_gemini_translated"
DEFAULT_REPORT_DIR = "translation_qa_reports"
DEFAULT_TRANSLATOR = "automate_gemini_gem.py"


TITLE_MAP = {
    "What Opened": "สิ่งใดเปิดออก?",
    "No What Is With Those Bastards": "ไม่สิ เจ้าพวกบ้านั่นมันเป็นอะไรกันไปหมด?",
    "Should I Show You What Real Trouble Looks Like": "ให้ข้าแสดงให้ดูไหมล่ะว่าความฉิบหายที่แท้จริงมันเป็นเช่นไร?",
    "So Prestigious Sects Dont Have Heads": "สำนักชื่อดังไม่มีหัวรั้นหรืออย่างไร?",
    "I Am The One Who Will Become The Sect Leader Of Mount Hua": "ข้าคือผู้ที่จะเป็นเจ้าสำนักฮวาซาน",
    "Life Is Inherently Unfair": "ชีวิตคนเรามันก็ไม่ยุติธรรมแบบนี้แหละ",
    "The End Is Another Beginning": "จุดจบคือการเริ่มต้นใหม่อีกครา",
    "I Will Always Be Your Wall": "ข้าจักเป็นปราการให้เจ้าเสมอ",
    "Can You Be The Embers": "เจ้าจะเป็นถ่านไฟนั้นได้หรือไม่",
    "I Wasnt Like That Back Then I Wasnt": "เมื่อก่อนข้าไม่ได้เป็นเช่นนั้น ไม่ได้เป็นเช่นนั้น",
    "A Gentleman Doesnt Put In Effort Without A Reason": "วิญญูชนไม่ลงแรงโดยไร้เหตุผล",
    "Where Is That Fucking Beggar Now": "ขอทานบัดซบนั่นอยู่ที่ใด",
    "Be It Shaolin Or Something Else": "จะเป็นเส้าหลินหรืออะไรก็ตาม",
    "That Is Something Well Have To Wait And See": "เรื่องนั้นคงต้องรอดูกันต่อไป",
    "Mount Hua Will Walk On The Path Of Mount Hua": "ฮวาซานจะก้าวเดินบนเส้นทางของฮวาซาน",
}


TERM_REPLACEMENTS = [
    ("น陽 (หนานหยาง)", "หนานหยาง"),
    ("报告", ""),
    ("觀眾 (ผู้ชม)", "ผู้ชม"),
    ("cảnh giác (ระแวดระวัง)", "ระแวดระวัง"),
    ("doting (รักใคร่เอ็นดู)", "เอ็นดู"),
    ("(체ดึก/Tamed)", ""),
    ("Reports", "ข่าวคราว"),
    ("Provincial", "มณฑล"),
    ("Martial Affairs", "วิชายุทธ์"),
    ("Muscle Memory", "ความเคยชินของร่างกาย"),
    ("Clear Flowing Water", "ธารพิสุทธิ์ชำระมลทิน"),
    ("Hundred Steps Divine Fist", "หมัดเทพร้อยก้าว"),
    ("Single-Edged Sword", "ดาบทะลวงบรรพต"),
    ("The Movement of Plum Blossom Resolve", "เพลงกระบี่ดอกเหมยตั้งมั่นปณิธาน"),
    ("Eun-Ryong", "อึนรยง"),
    ("pumpkin toadlets", "คางคกฟักทอง"),
    ("PR/N:", "หมายเหตุผู้แปล:"),
    ("วิชา ยุทธ์", "วิชายุทธ์"),
    ("อย่างนั้นร้อย", "อย่างนั้นรึ"),
    ("ยากกลืนกลืน", "ยากเย็น"),
    ("เสียงเสียงโด่งดัง", "มีชื่อเสียงโด่งดัง"),
    ("เสียงเสียง", "เสียง"),
    ("เสร็จสิ้นเสร็จสิ้น", "เสร็จสิ้น"),
    ("ธรรมดาธรรมดา", "ธรรมดา"),
    ("ทำเนียบทำเนียบ", "ทำเนียบ"),
    ("ศาตราศาสตรา", "ศาสตรา"),
    ("ทึ่", "ที่"),
    ("ออย่างนั้น", "อย่างนั้น"),
    ("โฟกัส", "จดจ่อ"),
    ("มารยาและ", "มารยาทและ"),
    ("ประสาทาน", "ท่านเจ้าสำนัก"),
    ("แมตช์", "การประลอง"),
    ("พวกเค้า", "พวกเขา"),
]


REGEX_REPLACEMENTS = [
    (re.compile(r'^\s*["“]?\s*suicide\s*["”]?\s*$', re.IGNORECASE | re.MULTILINE), ""),
    (re.compile(r"แ{2,}"), "แ"),
    (re.compile(r"ทแ"), "แ"),
    (re.compile(r"\s*\[[0-9]+\]"), ""),
    (re.compile(r"\s*\([^)]*(?:[A-Za-z一-龯ぁ-んァ-ン가-힣]|백|단악검|무진|허산)[^)]*\)"), ""),
    (re.compile(r"[ \t]+\n"), "\n"),
    (re.compile(r"\n{3,}"), "\n\n"),
]


ARTIFACT_PATTERNS = [
    ("placeholder_suicide", re.compile(r"\bsuicide\b", re.IGNORECASE)),
    ("latin_letters", re.compile(r"[A-Za-z]")),
    ("cjk_japanese_korean", re.compile(r"[一-龯ぁ-んァ-ン가-힣]")),
    ("duplicated_thai_leading_ae", re.compile(r"แ{2,}")),
    ("broken_thai_tae", re.compile(r"ทแ")),
    ("broken_thi", re.compile(r"ทึ่")),
    ("footnote_marker", re.compile(r"\[[0-9]+\]|PR/N|↩")),
    ("known_artifact_terms", re.compile(r"Reports|Provincial|Martial Affairs|Muscle Memory|Clear Flowing Water|Hundred Steps Divine Fist|Single-Edged Sword")),
    ("known_typo_terms", re.compile(r"วิชา ยุทธ์|อย่างนั้นร้อย|ยากกลืนกลืน|เสียงเสียง|ทำเนียบทำเนียบ|เสร็จสิ้นเสร็จสิ้น|ธรรมดาธรรมดา|ศาตราศาสตรา|มารยาและ|ออย่างนั้น")),
]


@dataclass
class ChapterRecord:
    number: int
    source_path: Path | None = None
    translation_path: Path | None = None
    fixes: list[str] = field(default_factory=list)
    artifacts_before: list[dict] = field(default_factory=list)
    artifacts_after: list[dict] = field(default_factory=list)


@dataclass
class TranslationRunResult:
    command: list[str] = field(default_factory=list)
    returncode: int = 0
    error: str = ""


def chapter_number(path: Path) -> int:
    try:
        return int(path.name.split("__", 1)[0])
    except ValueError:
        return 0


def chapter_files(folder: Path, start: int, end: int) -> dict[int, Path]:
    files = sorted(folder.glob("*.txt"), key=chapter_number)
    return {
        chapter_number(path): path
        for path in files
        if start <= chapter_number(path) <= end
    }


def expected_heading(source_path: Path) -> str:
    first_line = source_path.read_text(encoding="utf-8").splitlines()[0].strip()
    match = re.match(r"(\d+)\s+—\s+(.+?)\s*\((\d+)\)", first_line)
    if not match:
        number = chapter_number(source_path)
        return f"ตอนที่ {number}"

    number, english_title, part = match.groups()
    thai_title = TITLE_MAP.get(english_title)
    if not thai_title:
        cleaned = english_title.replace("_", " ")
        thai_title = cleaned
    return f"ตอนที่ {int(number)} — {thai_title} ({part})"


def has_thai_heading(text: str, number: int) -> bool:
    first = text.splitlines()[0].strip() if text.splitlines() else ""
    return first.startswith(f"ตอนที่ {number} ")


def scan_text(text: str, path: Path) -> list[dict]:
    findings = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for name, pattern in ARTIFACT_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "file": str(path),
                    "line": idx,
                    "type": name,
                    "text": line.strip()[:240],
                })
    return findings


def apply_safe_fixes(record: ChapterRecord, dry_run: bool = False) -> None:
    if not record.translation_path or not record.translation_path.exists():
        return

    path = record.translation_path
    original = path.read_text(encoding="utf-8")
    text = original

    if record.source_path and not has_thai_heading(text, record.number):
        heading = expected_heading(record.source_path)
        text = f"{heading}\n\n{text.lstrip()}"
        record.fixes.append(f"Added heading: {heading}")

    for old, new in TERM_REPLACEMENTS:
        if old in text:
            text = text.replace(old, new)
            record.fixes.append(f"Replaced `{old}` -> `{new}`")

    for pattern, replacement in REGEX_REPLACEMENTS:
        new_text = pattern.sub(replacement, text)
        if new_text != text:
            record.fixes.append(f"Applied regex fix: `{pattern.pattern}`")
            text = new_text

    if text != original and not dry_run:
        path.write_text(text.rstrip() + "\n", encoding="utf-8")


def run_translator(args: argparse.Namespace) -> TranslationRunResult:
    cmd = [
        "python",
        args.translator_script,
        "--start",
        str(args.start),
        "--end",
        str(args.end),
        "--input-dir",
        args.input_dir,
        "--output-dir",
        args.output_dir,
    ]

    if args.force_translate:
        cmd.append("--force")
    if args.use_copy_button:
        cmd.append("--use-copy-button")
    if args.continue_on_chapter_error:
        cmd.append("--continue-on-error")
    if args.timeout:
        cmd.extend(["--timeout", str(args.timeout)])
    if args.delay is not None:
        cmd.extend(["--delay", str(args.delay)])

    result = subprocess.run(cmd, check=False)
    run_result = TranslationRunResult(command=cmd, returncode=result.returncode)
    if result.returncode != 0:
        run_result.error = f"Translator exited with status {result.returncode}"
        if args.fail_fast_translate:
            raise subprocess.CalledProcessError(result.returncode, cmd)
    return run_result


def build_records(args: argparse.Namespace) -> list[ChapterRecord]:
    source_files = chapter_files(Path(args.input_dir), args.start, args.end)
    translated_files = chapter_files(Path(args.output_dir), args.start, args.end)

    records = []
    for number in range(args.start, args.end + 1):
        records.append(ChapterRecord(
            number=number,
            source_path=source_files.get(number),
            translation_path=translated_files.get(number),
        ))
    return records


def write_json_report(
    records: list[ChapterRecord],
    report_dir: Path,
    start: int,
    end: int,
    translation_run: TranslationRunResult | None = None,
) -> Path:
    payload = {
        "range": {"start": start, "end": end},
        "translation_run": {
            "command": translation_run.command,
            "returncode": translation_run.returncode,
            "error": translation_run.error,
        } if translation_run else None,
        "chapters": [
            {
                "number": record.number,
                "source_path": str(record.source_path) if record.source_path else None,
                "translation_path": str(record.translation_path) if record.translation_path else None,
                "fixes": record.fixes,
                "artifacts_before": record.artifacts_before,
                "artifacts_after": record.artifacts_after,
            }
            for record in records
        ],
    }
    path = report_dir / f"{start:04d}_{end:04d}_artifacts.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def translator_instruction(records: list[ChapterRecord]) -> str:
    remaining_types = sorted({
        artifact["type"]
        for record in records
        for artifact in record.artifacts_after
    })
    fixed_examples = []
    for record in records:
        fixed_examples.extend(record.fixes[:3])
    fixed_examples = fixed_examples[:12]

    lines = [
        "Translation instructions for the next revision:",
        "",
        "1. Output clean Thai martial-arts web novel prose only.",
        "   Do not leave English, Korean, Chinese, Japanese, Vietnamese, romanization, PR/N notes, footnote markers, or parenthetical glosses inside the chapter text.",
        "",
        "2. Always include the Thai chapter heading.",
        "   Format: ตอนที่ XXX — [Thai title] (part number)",
        "",
        "3. Remove machine-output artifacts before stylistic editing.",
        "   Watch for placeholders like `suicide`, duplicated Thai letters, broken particles, source-language leaks, and obvious typo patterns.",
        "",
        "4. Keep technique names in Thai only.",
        "   Use `ธารพิสุทธิ์ชำระมลทิน` for Clear Flowing Water and `หมัดเทพร้อยก้าว` for Hundred Steps Divine Fist.",
        "",
        "5. Preserve character voice and rhythm.",
        "   Chung Myung should be blunt, rude, shameless, funny, and sharp. Formal speakers should be dignified but concise.",
        "",
        "6. Keep jokes and action beats short.",
        "   Do not over-expand repeated chants, reactions, or fight movements into ornate prose.",
    ]

    if fixed_examples:
        lines.extend(["", "Safe fixes already applied in this QA pass:"])
        lines.extend(f"- {item}" for item in fixed_examples)

    if remaining_types:
        lines.extend(["", "Remaining artifact categories to review manually:"])
        lines.extend(f"- {item}" for item in remaining_types)

    return "\n".join(lines)


def critique_prompt(args: argparse.Namespace) -> str:
    return (
        "$critique-thai-novel-translation "
        f"Review chapters {args.start} to {args.end}. "
        f"Compare English in `{args.input_dir}` with Thai in `{args.output_dir}`. "
        "Return the table critique, priority cleanup checklist, overall assessment, "
        "and translator model instruction."
    )


def write_markdown_report(
    records: list[ChapterRecord],
    report_dir: Path,
    start: int,
    end: int,
    args: argparse.Namespace,
    translation_run: TranslationRunResult | None = None,
) -> Path:
    path = report_dir / f"{start:04d}_{end:04d}_report.md"
    missing_sources = [r.number for r in records if not r.source_path]
    missing_translations = [r.number for r in records if not r.translation_path]
    before_count = sum(len(r.artifacts_before) for r in records)
    after_count = sum(len(r.artifacts_after) for r in records)

    lines = [
        f"# Translation QA Report: {start}-{end}",
        "",
        "## Summary",
        "",
        f"- Source directory: `{args.input_dir}`",
        f"- Translation directory: `{args.output_dir}`",
        f"- Artifacts before fixes: `{before_count}`",
        f"- Artifacts after fixes: `{after_count}`",
        f"- Missing source chapters: `{missing_sources or 'none'}`",
        f"- Missing translation chapters: `{missing_translations or 'none'}`",
    ]
    if translation_run:
        lines.append(f"- Translator command: `{' '.join(translation_run.command)}`")
        lines.append(f"- Translator exit status: `{translation_run.returncode}`")
        if translation_run.error:
            lines.append(f"- Translator error: `{translation_run.error}`")
            lines.append("- QA continued using translation files that already exist.")

    lines.extend([
        "",
        "## Applied Fixes",
        "",
    ])

    any_fixes = False
    for record in records:
        if record.fixes:
            any_fixes = True
            lines.append(f"### Chapter {record.number}")
            lines.extend(f"- {fix}" for fix in record.fixes)
            lines.append("")
    if not any_fixes:
        lines.append("- No safe automatic fixes applied.")
        lines.append("")

    lines.extend([
        "## Remaining Artifact Findings",
        "",
    ])
    remaining = [
        artifact
        for record in records
        for artifact in record.artifacts_after
    ]
    if remaining:
        lines.append("| Ch. | Line | Type | Text |")
        lines.append("|---|---:|---|---|")
        for artifact in remaining[:200]:
            number = chapter_number(Path(artifact["file"]))
            escaped = artifact["text"].replace("|", "\\|")
            lines.append(f"| {number} | {artifact['line']} | `{artifact['type']}` | {escaped} |")
        if len(remaining) > 200:
            lines.append(f"| ... | ... | ... | {len(remaining) - 200} more findings omitted from Markdown report. See JSON. |")
    else:
        lines.append("- No remaining artifact findings from deterministic scan.")
    lines.append("")

    lines.extend([
        "## Critique Prompt",
        "",
        "```text",
        critique_prompt(args),
        "```",
        "",
        "## Translator Model Instruction",
        "",
        "```text",
        translator_instruction(records),
        "```",
        "",
    ])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run translation, deterministic QA cleanup, and report generation for Mount Hua chapters."
    )
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--translator-script", default=DEFAULT_TRANSLATOR)
    parser.add_argument("--skip-translate", action="store_true")
    parser.add_argument("--no-fix", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-translate", action="store_true")
    parser.add_argument("--use-copy-button", action="store_true")
    parser.add_argument(
        "--continue-on-chapter-error",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pass --continue-on-error to the Gemini translator so one timed-out chapter does not stop the batch.",
    )
    parser.add_argument(
        "--fail-fast-translate",
        action="store_true",
        help="Stop the workflow if the translator process exits non-zero.",
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--delay", type=int, default=5)
    args = parser.parse_args()

    if args.start > args.end:
        raise SystemExit("--start must be less than or equal to --end")

    translation_run = None
    if not args.skip_translate:
        translation_run = run_translator(args)

    records = build_records(args)
    for record in records:
        if record.translation_path and record.translation_path.exists():
            before = record.translation_path.read_text(encoding="utf-8")
            record.artifacts_before = scan_text(before, record.translation_path)
        if not args.no_fix:
            apply_safe_fixes(record, dry_run=args.dry_run)
        if record.translation_path and record.translation_path.exists():
            after = record.translation_path.read_text(encoding="utf-8")
            record.artifacts_after = scan_text(after, record.translation_path)

    report_dir = Path(args.report_dir)
    if not args.dry_run:
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = write_json_report(records, report_dir, args.start, args.end, translation_run)
        markdown_path = write_markdown_report(records, report_dir, args.start, args.end, args, translation_run)
        print(f"Wrote JSON report: {json_path}")
        print(f"Wrote Markdown report: {markdown_path}")
    else:
        before_count = sum(len(r.artifacts_before) for r in records)
        after_count = sum(len(r.artifacts_after) for r in records)
        print(f"Dry run complete. Artifacts before: {before_count}. Artifacts after: {after_count}.")


if __name__ == "__main__":
    main()
