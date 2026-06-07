import argparse
import html
import re
from dataclasses import dataclass
from pathlib import Path

from ebooklib import epub


DEFAULT_INPUT_DIR = "mount_hua_gemini_translated_256_330"
DEFAULT_OUTPUT_DIR = "ebooks"
DEFAULT_BOOK_PREFIX = "Return of the Mount Hua Sect"


@dataclass
class ChapterFile:
    path: Path
    number: int
    raw_title: str
    group_key: str
    group_title: str


def parse_chapter_file(path):
    match = re.match(r"^(\d{4})__(\d+)_(.+)\.txt$", path.name)
    if not match:
        return None

    number = int(match.group(2))
    title_slug = match.group(3)
    group_slug = re.sub(r"_?\d+$", "", title_slug).strip("_")
    title = title_slug.replace("_", " ")
    group_title = group_slug.replace("_", " ")

    return ChapterFile(
        path=path,
        number=number,
        raw_title=title,
        group_key=group_slug.lower(),
        group_title=group_title,
    )


def load_chapters(input_dir, start=None, end=None):
    chapters = []
    for path in sorted(Path(input_dir).glob("*.txt")):
        chapter = parse_chapter_file(path)
        if not chapter:
            continue
        if start is not None and chapter.number < start:
            continue
        if end is not None and chapter.number > end:
            continue
        chapters.append(chapter)

    return sorted(chapters, key=lambda chapter: chapter.number)


def group_by_title(chapters):
    groups = []
    current = []
    current_key = None

    for chapter in chapters:
        if current and chapter.group_key != current_key:
            groups.append(current)
            current = []

        current.append(chapter)
        current_key = chapter.group_key

    if current:
        groups.append(current)

    return groups


def group_by_size(chapters, group_size):
    return [
        chapters[index:index + group_size]
        for index in range(0, len(chapters), group_size)
    ]


def group_by_range(chapters, range_size):
    chapters_by_number = {chapter.number: chapter for chapter in chapters}
    if not chapters_by_number:
        return []

    first_range_start = ((min(chapters_by_number) - 1) // range_size) * range_size + 1
    last_range_start = ((max(chapters_by_number) - 1) // range_size) * range_size + 1
    groups = []

    for range_start in range(first_range_start, last_range_start + 1, range_size):
        range_end = range_start + range_size - 1
        numbers = range(range_start, range_end + 1)
        if not all(number in chapters_by_number for number in numbers):
            continue

        group = [chapters_by_number[number] for number in numbers]
        for chapter in group:
            chapter.group_key = f"{range_start}-{range_end}"
            chapter.group_title = f"Chapters {range_start}-{range_end}"
        groups.append(group)

    return groups


def safe_filename(value):
    value = re.sub(r"[^A-Za-z0-9 _-]+", "", value)
    value = re.sub(r"\s+", "_", value.strip())
    return value or "ebook"


def paragraph_html(text):
    blocks = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        escaped = "<br/>".join(html.escape(line) for line in lines)
        blocks.append(f"<p>{escaped}</p>")
    return "\n".join(blocks)


def chapter_title_and_body(text, fallback_title):
    lines = text.splitlines()
    title = lines[0].strip() if lines else fallback_title
    body = "\n".join(lines[1:]).strip() if lines else ""
    return title or fallback_title, body


def make_chapter_document(chapter, index):
    text = chapter.path.read_text(encoding="utf-8").strip()
    title, body = chapter_title_and_body(text, chapter.raw_title or f"Chapter {chapter.number}")

    document = epub.EpubHtml(
        title=title,
        file_name=f"chapter_{index:03d}_{chapter.number}.xhtml",
        lang="th",
    )
    content = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="th">
<head>
  <title>{html.escape(title)}</title>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  {paragraph_html(body)}
</body>
</html>
"""
    document.set_content(content.encode("utf-8"))
    return document


def write_epub(group, output_dir, book_prefix, author):
    start = group[0].number
    end = group[-1].number
    group_title = group[0].group_title
    is_range_group = group[0].group_key == f"{start}-{end}"

    if is_range_group:
        title = f"{book_prefix} {start}-{end}"
        filename = f"{safe_filename(book_prefix)}_{start}-{end}.epub"
        identifier_suffix = f"{start}-{end}"
    else:
        title = f"{book_prefix} {start}-{end} - {group_title}"
        filename = f"{safe_filename(book_prefix)}_{start}-{end}_{safe_filename(group_title)}.epub"
        identifier_suffix = f"{start}-{end}-{safe_filename(group_title).lower()}"

    output_path = Path(output_dir) / filename

    book = epub.EpubBook()
    book.set_identifier(f"mount-hua-{identifier_suffix}")
    book.set_title(title)
    book.set_language("th")
    book.add_author(author)

    style = epub.EpubItem(
        uid="style",
        file_name="style/book.css",
        media_type="text/css",
        content="""
body {
  font-family: serif;
  line-height: 1.75;
  margin: 5%;
}
h1 {
  font-size: 1.35em;
  line-height: 1.35;
  margin-bottom: 1.5em;
}
p {
  margin: 0 0 1em 0;
}
""",
    )
    book.add_item(style)

    documents = []
    for index, chapter in enumerate(group, start=1):
        document = make_chapter_document(chapter, index)
        document.add_item(style)
        book.add_item(document)
        documents.append(document)

    book.toc = tuple(documents)
    book.spine = ["nav", *documents]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)
    return output_path


def preview_groups(groups):
    for group in groups:
        print(
            f"{group[0].number}-{group[-1].number}: "
            f"{group[0].group_title} ({len(group)} chapters)"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Create EPUB files from translated Mount Hua chapter text files."
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--book-prefix", default=DEFAULT_BOOK_PREFIX)
    parser.add_argument("--author", default="Rafaelx")
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument(
        "--group-by",
        choices=["title", "range", "size"],
        default="range",
        help=(
            "range groups complete episode ranges like 301-310; "
            "title groups same chapter names; size groups fixed chapter counts."
        ),
    )
    parser.add_argument("--group-size", type=int, default=10)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Only print planned EPUB groups; do not create files.",
    )
    args = parser.parse_args()

    chapters = load_chapters(args.input_dir, args.start, args.end)
    if not chapters:
        raise SystemExit(f"No chapter files found in {args.input_dir}")

    if args.group_by == "title":
        groups = group_by_title(chapters)
    elif args.group_by == "range":
        groups = group_by_range(chapters, args.group_size)
    else:
        groups = group_by_size(chapters, args.group_size)

    if not groups:
        raise SystemExit(
            f"No complete {args.group_size}-chapter groups found in {args.input_dir}"
        )

    preview_groups(groups)
    if args.preview:
        return

    for group in groups:
        output_path = write_epub(group, args.output_dir, args.book_prefix, args.author)
        print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
