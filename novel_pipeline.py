import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_SOURCE_DIR = "novel_chapters"
DEFAULT_TRANSLATED_DIR = "novel_gemini_translated"
DEFAULT_FINAL_DIR = "novel_final"
DEFAULT_EPUB_DIR = "ebooks"
DEFAULT_REPORT_DIR = "pipeline_reports"
DEFAULT_BOOK_PREFIX = "Return of the Mount Hua Sect"
DEFAULT_AUTHOR = "Rafaelx"


LATIN_RE = re.compile(r"[A-Za-z]")
CJK_KOREAN_RE = re.compile(r"[一-龯ぁ-んァ-ン가-힣]")
KNOWN_ARTIFACT_RE = re.compile(
    r"PR/N|Translator|Reports|Provincial|Martial Affairs|Muscle Memory|"
    r"Clear Flowing Water|Hundred Steps Divine Fist|Single-Edged Sword",
    re.IGNORECASE,
)
SUSPICIOUS_PRONOUN_RE = re.compile(r"คุณ|พวกคุณ|นาย|พวกนาย|เธอ|หล่อน")
THAI_HEADING_RE = re.compile(r"^ตอนที่\s+\d+")


@dataclass
class VerificationFinding:
    severity: str
    check: str
    path: str
    line: int | None = None
    text: str = ""


@dataclass
class VerificationResult:
    findings: list[VerificationFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[VerificationFinding]:
        return [item for item in self.findings if item.severity == "error"]

    @property
    def warnings(self) -> list[VerificationFinding]:
        return [item for item in self.findings if item.severity == "warning"]

    def is_clean(self) -> bool:
        return not self.findings


def chapter_number(path: Path) -> int:
    match = re.match(r"^(\d+)", path.name)
    if not match:
        return 0
    return int(match.group(1))


def chapter_files(folder: Path, start: int, end: int) -> dict[int, Path]:
    if not folder.exists():
        return {}

    files = sorted(folder.glob("*.txt"), key=chapter_number)
    return {
        chapter_number(path): path
        for path in files
        if start <= chapter_number(path) <= end
    }


def run_command(cmd: list[str], cwd: Path) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def validate_source_files(args: argparse.Namespace) -> None:
    source_dir = Path(args.input_dir)
    files = chapter_files(source_dir, args.start, args.end)
    missing = [
        number
        for number in range(args.start, args.end + 1)
        if number not in files
    ]

    if missing:
        raise SystemExit(
            f"Missing English source chapters in {source_dir}: "
            f"{', '.join(str(number) for number in missing)}"
        )

    print(f"Found {len(files)} English source chapters in {source_dir}.")


def run_gemini_translation(args: argparse.Namespace, cwd: Path) -> None:
    cmd = [
        sys.executable,
        "automate_gemini_gem.py",
        "--input-dir",
        args.input_dir,
        "--output-dir",
        args.translated_dir,
        "--start",
        str(args.start),
        "--end",
        str(args.end),
        "--timeout",
        str(args.timeout),
        "--delay",
        str(args.delay),
    ]

    if args.force_translate:
        cmd.append("--force")
    if args.use_copy_button:
        cmd.append("--use-copy-button")
    if args.continue_on_chapter_error:
        cmd.append("--continue-on-error")

    run_command(cmd, cwd)


def prepare_final_files(args: argparse.Namespace) -> None:
    translated_dir = Path(args.translated_dir)
    final_dir = Path(args.final_dir)
    translated_files = chapter_files(translated_dir, args.start, args.end)

    missing = [
        number
        for number in range(args.start, args.end + 1)
        if number not in translated_files
    ]
    if missing:
        raise SystemExit(
            f"Missing translated chapters in {translated_dir}: "
            f"{', '.join(str(number) for number in missing)}"
        )

    final_dir.mkdir(parents=True, exist_ok=True)
    copied = 0

    for number in range(args.start, args.end + 1):
        source = translated_files[number]
        target = final_dir / source.name

        if target.exists() and target.stat().st_size > 0 and not args.force_final:
            continue

        shutil.copy2(source, target)
        ensure_chapter_heading(target)
        copied += 1

    print(f"Prepared {copied} final files in {final_dir}.")


def filename_heading(path: Path) -> str:
    match = re.match(r"^(\d+)__(\d+)_(.+)\.txt$", path.name)
    if not match:
        number = chapter_number(path)
        return f"ตอนที่ {number}"

    _, chapter, title_slug = match.groups()
    title = title_slug.replace("_", " ")
    part_match = re.match(r"^(.+)\s+(\d+)$", title)
    if part_match:
        title, part = part_match.groups()
        return f"ตอนที่ {int(chapter)} - {title} ({part})"

    return f"ตอนที่ {int(chapter)} - {title}"


def has_chapter_heading(text: str, number: int) -> bool:
    first = first_nonempty_line(text)
    if first.startswith(f"ตอนที่ {number}"):
        return True
    if re.match(rf"^{number}\s+[—-]\s+.+", first):
        return True
    if re.match(rf"^Chapter\s+{number}\b", first, re.IGNORECASE):
        return True
    return False


def ensure_chapter_heading(path: Path) -> bool:
    number = chapter_number(path)
    text = path.read_text(encoding="utf-8")
    if has_chapter_heading(text, number):
        return False

    heading = filename_heading(path)
    path.write_text(f"{heading}\n\n{text.lstrip()}", encoding="utf-8")
    return True


def ensure_final_headings(args: argparse.Namespace) -> None:
    final_dir = Path(args.final_dir)
    files = chapter_files(final_dir, args.start, args.end)
    changed = 0

    for number in range(args.start, args.end + 1):
        path = files.get(number)
        if path and ensure_chapter_heading(path):
            changed += 1

    print(f"Ensured chapter headings in {final_dir}: {changed} file(s) updated.")


def codex_prompt(args: argparse.Namespace) -> str:
    return (
        "$thai-novel-translation-pipeline "
        f"chapter {args.start} to {args.end} auto apply. "
        f"Use English source files from `{args.input_dir}` and Thai files from "
        f"`{args.final_dir}`. Edit only files in `{args.final_dir}` for this "
        "chapter range. Preserve raw Gemini files. Run the bounded improvement "
        "loop from the skill. If a chapter heading was generated from the "
        "filename and still contains an English title, translate the title part "
        "into natural Thai while preserving the format `ตอนที่ N - ชื่อไทย (part)`. "
        "Then report passes run, stop reason, verification scans, and any "
        "unresolved risks."
    )


def run_codex_polish(args: argparse.Namespace, cwd: Path) -> None:
    cmd = [
        "codex",
        "exec",
        "-C",
        str(cwd),
        "--sandbox",
        "danger-full-access",
        codex_prompt(args),
    ]
    run_command(cmd, cwd)


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def add_finding(
    result: VerificationResult,
    severity: str,
    check: str,
    path: Path,
    line: int | None = None,
    text: str = "",
) -> None:
    result.findings.append(
        VerificationFinding(
            severity=severity,
            check=check,
            path=str(path),
            line=line,
            text=text.strip()[:240],
        )
    )


def verify_final_files(args: argparse.Namespace) -> VerificationResult:
    final_dir = Path(args.final_dir)
    files = chapter_files(final_dir, args.start, args.end)
    result = VerificationResult()

    for number in range(args.start, args.end + 1):
        path = files.get(number)
        if not path:
            add_finding(result, "error", "missing_chapter", final_dir / f"{number:04d}*.txt")
            continue

        text = path.read_text(encoding="utf-8")
        if not text.strip():
            add_finding(result, "error", "empty_file", path)
            continue

        heading = first_nonempty_line(text)
        has_heading = THAI_HEADING_RE.search(heading)
        if not has_heading:
            add_finding(result, "warning", "missing_or_non_thai_heading", path, 1, heading)
        elif LATIN_RE.search(heading):
            add_finding(result, "warning", "english_heading_title", path, 1, heading)

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line_number == 1 and has_heading:
                continue
            if LATIN_RE.search(line):
                add_finding(result, "error", "latin_text_leftover", path, line_number, line)
            if CJK_KOREAN_RE.search(line):
                add_finding(result, "error", "cjk_or_korean_leftover", path, line_number, line)
            if KNOWN_ARTIFACT_RE.search(line):
                add_finding(result, "error", "known_artifact_term", path, line_number, line)
            if SUSPICIOUS_PRONOUN_RE.search(line):
                add_finding(result, "warning", "suspicious_pronoun", path, line_number, line)

    print_verification_summary(result)
    return result


def print_verification_summary(result: VerificationResult) -> None:
    print(
        "Verification: "
        f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)."
    )

    preview_limit = 30
    for finding in result.findings[:preview_limit]:
        location = finding.path
        if finding.line is not None:
            location += f":{finding.line}"
        print(f"[{finding.severity}] {finding.check}: {location}")
        if finding.text:
            print(f"  {finding.text}")

    if len(result.findings) > preview_limit:
        print(f"... {len(result.findings) - preview_limit} more finding(s) omitted.")


def write_verification_report(
    args: argparse.Namespace,
    result: VerificationResult,
) -> Path:
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{args.start:04d}_{args.end:04d}_verification.md"

    lines = [
        f"# Verification Report: {args.start}-{args.end}",
        "",
        f"- Final directory: `{args.final_dir}`",
        f"- Errors: `{len(result.errors)}`",
        f"- Warnings: `{len(result.warnings)}`",
        "",
    ]

    if result.findings:
        lines.extend(["| Severity | Check | Location | Text |", "|---|---|---|---|"])
        for finding in result.findings:
            location = finding.path
            if finding.line is not None:
                location += f":{finding.line}"
            text = finding.text.replace("|", "\\|")
            lines.append(
                f"| {finding.severity} | `{finding.check}` | `{location}` | {text} |"
            )
    else:
        lines.append("No verification findings.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote verification report: {path}")
    return path


def enforce_verification_gate(args: argparse.Namespace, result: VerificationResult) -> None:
    if result.errors and not args.allow_verify_errors:
        raise SystemExit(
            "Verification found error-level issues. Fix them or rerun with "
            "--allow-verify-errors."
        )

    if result.warnings and args.fail_on_verify_warnings:
        raise SystemExit(
            "Verification found warning-level issues. Review them or rerun without "
            "--fail-on-verify-warnings."
        )


def run_epub_builder(args: argparse.Namespace, cwd: Path) -> None:
    cmd = [
        sys.executable,
        "make_epub_batches.py",
        "--input-dir",
        args.final_dir,
        "--output-dir",
        args.epub_dir,
        "--book-prefix",
        args.book_prefix,
        "--author",
        args.author,
        "--start",
        str(args.start),
        "--end",
        str(args.end),
        "--group-by",
        epub_group_by(args),
        "--group-size",
        str(epub_group_size(args)),
    ]

    if args.epub_preview:
        cmd.append("--preview")

    run_command(cmd, cwd)


def epub_group_by(args: argparse.Namespace) -> str:
    if args.group_by:
        return args.group_by
    return "size"


def epub_group_size(args: argparse.Namespace) -> int:
    if args.group_size:
        return args.group_size
    return args.end - args.start + 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the novel translation pipeline from manually scraped English "
            "chapters to final EPUB."
        )
    )
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--input-dir", default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--translated-dir", default=DEFAULT_TRANSLATED_DIR)
    parser.add_argument("--final-dir", default=DEFAULT_FINAL_DIR)
    parser.add_argument("--epub-dir", default=DEFAULT_EPUB_DIR)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--book-prefix", default=DEFAULT_BOOK_PREFIX)
    parser.add_argument("--author", default=DEFAULT_AUTHOR)

    parser.add_argument("--all", action="store_true", help="Run translate, polish, verify, and EPUB.")
    parser.add_argument("--translate", action="store_true", help="Run Gemini translation.")
    parser.add_argument("--prepare-final", action="store_true", help="Copy translated files to final dir.")
    parser.add_argument("--polish-with-codex", action="store_true", help="Run Codex Thai polishing skill.")
    parser.add_argument("--verify", action="store_true", help="Run final verification scans.")
    parser.add_argument("--make-epub", action="store_true", help="Build EPUB from final dir.")

    parser.add_argument("--force-translate", action="store_true")
    parser.add_argument("--force-final", action="store_true", help="Overwrite existing files in final dir.")
    parser.add_argument("--use-copy-button", action="store_true")
    parser.add_argument(
        "--continue-on-chapter-error",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--delay", type=int, default=5)

    parser.add_argument("--allow-verify-errors", action="store_true")
    parser.add_argument("--fail-on-verify-warnings", action="store_true")

    parser.add_argument(
        "--group-by",
        choices=["title", "range", "size"],
        help="EPUB grouping. Default is size, using the selected chapter count.",
    )
    parser.add_argument(
        "--group-size",
        type=int,
        help="EPUB group size. Default is --end - --start + 1.",
    )
    parser.add_argument("--epub-preview", action="store_true")

    args = parser.parse_args()
    if args.start > args.end:
        raise SystemExit("--start must be less than or equal to --end")

    if not any([
        args.all,
        args.translate,
        args.prepare_final,
        args.polish_with_codex,
        args.verify,
        args.make_epub,
    ]):
        raise SystemExit(
            "No pipeline stage selected. Use --all or choose one of "
            "--translate, --prepare-final, --polish-with-codex, --verify, --make-epub."
        )

    return args


def main() -> None:
    args = parse_args()
    cwd = Path(__file__).resolve().parent

    validate_source_files(args)

    if args.all or args.translate:
        run_gemini_translation(args, cwd)

    if args.all or args.prepare_final or args.polish_with_codex:
        prepare_final_files(args)

    if args.all or args.polish_with_codex or args.verify or args.make_epub:
        ensure_final_headings(args)

    if args.all or args.polish_with_codex:
        run_codex_polish(args, cwd)

    if args.all or args.polish_with_codex:
        ensure_final_headings(args)

    verification_result = None
    if args.all or args.verify or args.make_epub:
        verification_result = verify_final_files(args)
        write_verification_report(args, verification_result)
        enforce_verification_gate(args, verification_result)

    if args.all or args.make_epub:
        run_epub_builder(args, cwd)


if __name__ == "__main__":
    main()
