import argparse
import html
import mimetypes
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo
import xml.etree.ElementTree as ET


OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"

MANAGED_COVER_IDS = {"cover-image", "cover-page"}
MANAGED_COVER_HREFS = {"images/cover.png", "images/cover.jpg", "images/cover.jpeg", "images/cover.webp", "cover.xhtml"}
CHARACTER_PAGE_ID = "character-intro"
CHARACTER_PAGE_HREF = "characters.xhtml"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ChapterRange:
    start: int
    end: int

    @property
    def key(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass
class CoverMatch:
    image_path: Path
    score: int


@dataclass
class CharacterEntry:
    group: str
    name: str
    summary: str


@dataclass
class ApplyResult:
    chapter_range: ChapterRange
    epub_path: Path
    cover_path: Path | None = None
    character_intro: bool = False
    status: str = "skipped"
    warnings: list[str] = field(default_factory=list)
    backup_path: Path | None = None


def q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def register_namespaces() -> None:
    ET.register_namespace("", OPF_NS)
    ET.register_namespace("dc", DC_NS)
    ET.register_namespace("epub", EPUB_NS)


def extract_range(path: Path) -> ChapterRange | None:
    match = re.search(r"(?<!\d)(\d{3,4})\D+(\d{3,4})(?!\d)", path.stem)
    if not match:
        return None

    start, end = (int(value) for value in match.groups())
    if start > end:
        return None
    return ChapterRange(start, end)


def score_image_name(path: Path, chapter_range: ChapterRange) -> int:
    stem = path.stem.lower()
    exact_forms = {
        chapter_range.key,
        chapter_range.key.replace("-", "_"),
        f"{chapter_range.start}_{chapter_range.end}",
        f"{chapter_range.start}-{chapter_range.end}",
    }
    if stem in exact_forms:
        return 0
    if stem in {f"cover-{chapter_range.key}", f"cover_{chapter_range.start}_{chapter_range.end}"}:
        return 1
    if "cover" in stem:
        return 2
    return 3


def collect_cover_images(images_dir: Path) -> dict[ChapterRange, list[CoverMatch]]:
    matches: dict[ChapterRange, list[CoverMatch]] = {}
    for image_path in sorted(images_dir.iterdir()):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        chapter_range = extract_range(image_path)
        if not chapter_range:
            continue

        matches.setdefault(chapter_range, []).append(
            CoverMatch(image_path=image_path, score=score_image_name(image_path, chapter_range))
        )

    for cover_matches in matches.values():
        cover_matches.sort(key=lambda item: (item.score, item.image_path.name.lower()))
    return matches


def media_type_for(path: Path) -> str:
    if path.suffix.lower() == ".jpg":
        return "image/jpeg"
    media_type, _ = mimetypes.guess_type(path.name)
    if not media_type:
        raise ValueError(f"Unsupported cover image type: {path}")
    return media_type


def cover_archive_name(cover_path: Path) -> str:
    suffix = cover_path.suffix.lower()
    if suffix == ".jpg":
        suffix = ".jpeg"
    return f"EPUB/images/cover{suffix}"


def cover_href(cover_path: Path) -> str:
    return cover_archive_name(cover_path).removeprefix("EPUB/")


def serialize_xml(root: ET.Element, default_namespace: str, extra_namespaces: list[tuple[str, str]] | None = None) -> bytes:
    ET.register_namespace("", default_namespace)
    for prefix, namespace in extra_namespaces or []:
        ET.register_namespace(prefix, namespace)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def image_page(title: str, image_href: str) -> bytes:
    return f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" lang="th" xml:lang="th">
  <head>
    <title>{title}</title>
    <link href="style/book.css" rel="stylesheet" type="text/css"/>
  </head>
  <body class="cover-page" epub:type="cover">
    <figure>
      <img alt="{title}" class="cover-image" src="{image_href}"/>
    </figure>
  </body>
</html>
""".encode("utf-8")


def read_character_entries(path: Path) -> list[CharacterEntry]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        columns = line.split("\t")
        if line_number == 1 and columns[:3] == ["กลุ่ม/สำนัก", "ชื่อตัวละคร (ไทย)", "ข้อมูลอย่างสั้น"]:
            continue
        if line_number == 1 and columns[:3] == ["ชื่อตัวละคร (ไทย)", "บทบาท/สถานะ", "ฉายา/สมญานาม"]:
            continue
        if len(columns) == 3:
            rows.append(CharacterEntry(group=columns[0], name=columns[1], summary=columns[2]))
        elif len(columns) == 4:
            summary = f"{columns[2]} — {columns[3]}"
            rows.append(CharacterEntry(group=columns[0], name=columns[1], summary=summary))
        else:
            raise ValueError(f"{path}:{line_number}: expected 3 or 4 tab-separated columns")
    if not rows:
        raise ValueError(f"No character entries found in {path}")
    return rows


def character_page(entries: list[CharacterEntry]) -> bytes:
    groups: dict[str, list[CharacterEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.group, []).append(entry)

    sections = []
    for group, group_entries in groups.items():
        items = "\n".join(
            "      <li>"
            f"<strong>{html.escape(entry.name)}</strong> "
            f"{html.escape(entry.summary)}"
            "</li>"
            for entry in group_entries
        )
        sections.append(
            f"""    <section class="character-group">
      <h2>{html.escape(group)}</h2>
      <ol class="character-list">
{items}
      </ol>
    </section>"""
        )
    body = "\n".join(sections)
    return f"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE html>
<html xmlns="{XHTML_NS}" xmlns:epub="{EPUB_NS}" lang="th" xml:lang="th">
  <head>
    <title>แนะนำตัวละคร</title>
    <link href="style/book.css" rel="stylesheet" type="text/css"/>
  </head>
  <body class="character-page">
    <h1>แนะนำตัวละคร</h1>
{body}
  </body>
</html>
""".encode("utf-8")


def ensure_front_matter_css(entries: dict[str, bytes]) -> None:
    css_name = "EPUB/style/book.css"
    css = entries.get(css_name, b"").decode("utf-8")
    front_matter_css = """

body.cover-page {
  margin: 0;
  padding: 0;
  text-align: center;
}
body.cover-page figure {
  margin: 0;
  padding: 0;
}
.cover-image {
  display: block;
  height: auto;
  margin: 0 auto;
  max-height: 100vh;
  max-width: 100%;
  width: auto;
}
body.character-page {
  margin: 5%;
}
body.character-page h2 {
  font-size: 1.1em;
  margin: 1.4em 0 0.45em 0;
}
.character-list {
  line-height: 1.55;
  margin: 0 0 1em 1.4em;
  padding: 0;
}
.character-list li {
  margin: 0 0 0.5em 0;
}
.character-table {
  border-collapse: collapse;
  font-size: 0.9em;
  line-height: 1.45;
  width: 100%;
}
.character-table th,
.character-table td {
  border-bottom: 1px solid #999;
  padding: 0.45em 0.35em;
  text-align: left;
  vertical-align: top;
}
.character-table th {
  font-weight: bold;
}
"""
    if ".cover-image" not in css or ".character-list" not in css:
        entries[css_name] = (css.rstrip() + front_matter_css).encode("utf-8")


def remove_existing_cover_metadata(metadata: ET.Element, manifest: ET.Element, spine: ET.Element) -> None:
    for meta in list(metadata):
        if meta.tag == q(OPF_NS, "meta") and meta.get("name") == "cover":
            metadata.remove(meta)

    for item in list(manifest):
        if item.get("id") in MANAGED_COVER_IDS or item.get("href") in MANAGED_COVER_HREFS:
            manifest.remove(item)

    for itemref in list(spine):
        if itemref.get("idref") == "cover-page":
            spine.remove(itemref)


def update_modified_time(metadata: ET.Element) -> None:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for meta in metadata:
        if meta.tag == q(OPF_NS, "meta") and meta.get("property") == "dcterms:modified":
            meta.text = timestamp
            return
    ET.SubElement(metadata, q(OPF_NS, "meta"), {"property": "dcterms:modified"}).text = timestamp


def insert_cover_in_spine(spine: ET.Element) -> None:
    itemrefs = list(spine)
    insert_index = 0
    for index, itemref in enumerate(itemrefs):
        if itemref.get("idref") == "nav":
            itemref.set("linear", "no")
            insert_index = index + 1
            break
    spine.insert(insert_index, ET.Element(q(OPF_NS, "itemref"), {"idref": "cover-page"}))


def remove_existing_character_metadata(manifest: ET.Element, spine: ET.Element) -> None:
    for item in list(manifest):
        if item.get("id") == CHARACTER_PAGE_ID or item.get("href") == CHARACTER_PAGE_HREF:
            manifest.remove(item)

    for itemref in list(spine):
        if itemref.get("idref") == CHARACTER_PAGE_ID:
            spine.remove(itemref)


def insert_character_in_spine(spine: ET.Element) -> None:
    itemrefs = list(spine)
    insert_index = 0
    for index, itemref in enumerate(itemrefs):
        idref = itemref.get("idref", "")
        if idref == "nav":
            itemref.set("linear", "no")
            continue
        if idref.startswith("chapter_"):
            insert_index = index
            break
        insert_index = index + 1
    spine.insert(insert_index, ET.Element(q(OPF_NS, "itemref"), {"idref": CHARACTER_PAGE_ID}))


def update_opf(
    entries: dict[str, bytes],
    cover_path: Path | None = None,
    characters: list[CharacterEntry] | None = None,
) -> None:
    opf_name = "EPUB/content.opf"
    root = ET.fromstring(entries[opf_name])
    metadata = root.find(q(OPF_NS, "metadata"))
    manifest = root.find(q(OPF_NS, "manifest"))
    spine = root.find(q(OPF_NS, "spine"))
    if metadata is None or manifest is None or spine is None:
        raise ValueError("Invalid OPF: missing metadata, manifest, or spine")

    if cover_path:
        remove_existing_cover_metadata(metadata, manifest, spine)
    if characters:
        remove_existing_character_metadata(manifest, spine)
    update_modified_time(metadata)

    if cover_path:
        image_href = cover_href(cover_path)
        ET.SubElement(metadata, q(OPF_NS, "meta"), {"name": "cover", "content": "cover-image"})
        ET.SubElement(
            manifest,
            q(OPF_NS, "item"),
            {
                "href": image_href,
                "id": "cover-image",
                "media-type": media_type_for(cover_path),
                "properties": "cover-image",
            },
        )
        ET.SubElement(
            manifest,
            q(OPF_NS, "item"),
            {"href": "cover.xhtml", "id": "cover-page", "media-type": "application/xhtml+xml"},
        )
        insert_cover_in_spine(spine)

    if characters:
        ET.SubElement(
            manifest,
            q(OPF_NS, "item"),
            {"href": CHARACTER_PAGE_HREF, "id": CHARACTER_PAGE_ID, "media-type": "application/xhtml+xml"},
        )
        insert_character_in_spine(spine)

    entries[opf_name] = serialize_xml(root, OPF_NS, [("dc", DC_NS)])


def update_nav(entries: dict[str, bytes], include_cover: bool = False, include_characters: bool = False) -> None:
    nav_name = "EPUB/nav.xhtml"
    if nav_name not in entries:
        return

    root = ET.fromstring(entries[nav_name])
    ol = root.find(f".//{q(XHTML_NS, 'nav')}/{q(XHTML_NS, 'ol')}")
    if ol is None:
        return

    for li in list(ol):
        anchor = li.find(q(XHTML_NS, "a"))
        if anchor is None:
            continue
        href = anchor.get("href")
        if include_cover and href == "cover.xhtml":
            ol.remove(li)
        elif include_characters and href == CHARACTER_PAGE_HREF:
            ol.remove(li)

    if include_cover:
        li = ET.Element(q(XHTML_NS, "li"))
        anchor = ET.SubElement(li, q(XHTML_NS, "a"), {"href": "cover.xhtml"})
        anchor.text = "ปก"
        ol.insert(0, li)

    if include_characters:
        insert_index = len(list(ol))
        for index, li_item in enumerate(list(ol)):
            anchor = li_item.find(q(XHTML_NS, "a"))
            if anchor is not None and (anchor.get("href") or "").startswith("chapter_"):
                insert_index = index
                break
        li = ET.Element(q(XHTML_NS, "li"))
        anchor = ET.SubElement(li, q(XHTML_NS, "a"), {"href": CHARACTER_PAGE_HREF})
        anchor.text = "แนะนำตัวละคร"
        ol.insert(insert_index, li)
    entries[nav_name] = serialize_xml(root, XHTML_NS, [("epub", EPUB_NS)])


def update_ncx(entries: dict[str, bytes], include_cover: bool = False, include_characters: bool = False) -> None:
    ncx_name = "EPUB/toc.ncx"
    if ncx_name not in entries:
        return

    root = ET.fromstring(entries[ncx_name])
    nav_map = root.find(q(NCX_NS, "navMap"))
    if nav_map is None:
        return

    for nav_point in list(nav_map):
        if include_cover and nav_point.get("id") == "cover-page":
            nav_map.remove(nav_point)
        elif include_characters and nav_point.get("id") == CHARACTER_PAGE_ID:
            nav_map.remove(nav_point)

    if include_cover:
        nav_point = ET.Element(q(NCX_NS, "navPoint"), {"id": "cover-page"})
        nav_label = ET.SubElement(nav_point, q(NCX_NS, "navLabel"))
        text = ET.SubElement(nav_label, q(NCX_NS, "text"))
        text.text = "ปก"
        ET.SubElement(nav_point, q(NCX_NS, "content"), {"src": "cover.xhtml"})
        nav_map.insert(0, nav_point)

    if include_characters:
        insert_index = len(list(nav_map))
        for index, nav_point_item in enumerate(list(nav_map)):
            if (nav_point_item.get("id") or "").startswith("chapter_"):
                insert_index = index
                break
        nav_point = ET.Element(q(NCX_NS, "navPoint"), {"id": CHARACTER_PAGE_ID})
        nav_label = ET.SubElement(nav_point, q(NCX_NS, "navLabel"))
        text = ET.SubElement(nav_label, q(NCX_NS, "text"))
        text.text = "แนะนำตัวละคร"
        ET.SubElement(nav_point, q(NCX_NS, "content"), {"src": CHARACTER_PAGE_HREF})
        nav_map.insert(insert_index, nav_point)
    entries[ncx_name] = serialize_xml(root, NCX_NS)


def write_epub(epub_path: Path, entries: dict[str, bytes]) -> None:
    tmp_path = epub_path.with_suffix(".epub.tmp")
    mimetype = entries.pop("mimetype")
    with ZipFile(tmp_path, "w") as zout:
        info = ZipInfo("mimetype")
        info.compress_type = ZIP_STORED
        zout.writestr(info, mimetype)

        for name, data in entries.items():
            info = ZipInfo(name)
            info.compress_type = ZIP_DEFLATED
            zout.writestr(info, data)
    tmp_path.replace(epub_path)


def apply_front_matter(
    epub_path: Path,
    cover_path: Path | None = None,
    characters: list[CharacterEntry] | None = None,
    backup: bool = True,
) -> Path | None:
    backup_path = epub_path.with_suffix(".epub.bak")
    if backup and not backup_path.exists():
        shutil.copy2(epub_path, backup_path)

    with ZipFile(epub_path, "r") as zin:
        entries = {name: zin.read(name) for name in zin.namelist()}

    if "mimetype" not in entries or "EPUB/content.opf" not in entries:
        raise ValueError("Invalid EPUB: missing mimetype or EPUB/content.opf")

    register_namespaces()
    if cover_path:
        for href in MANAGED_COVER_HREFS:
            entries.pop(f"EPUB/{href}", None)
        image_href = cover_href(cover_path)
        archive_name = f"EPUB/{image_href}"
        entries[archive_name] = cover_path.read_bytes()
        entries["EPUB/cover.xhtml"] = image_page("ปก", image_href)
    if characters:
        entries[f"EPUB/{CHARACTER_PAGE_HREF}"] = character_page(characters)
    ensure_front_matter_css(entries)
    update_opf(entries, cover_path=cover_path, characters=characters)
    update_nav(entries, include_cover=cover_path is not None, include_characters=characters is not None)
    update_ncx(entries, include_cover=cover_path is not None, include_characters=characters is not None)
    write_epub(epub_path, entries)

    with ZipFile(epub_path, "r") as zout:
        bad_file = zout.testzip()
        if bad_file:
            raise ValueError(f"EPUB zip integrity failed at {bad_file}")
        if zout.namelist()[0] != "mimetype":
            raise ValueError("EPUB mimetype is not the first archive entry")

    return backup_path if backup_path.exists() else None


def pick_cover(chapter_range: ChapterRange, covers: dict[ChapterRange, list[CoverMatch]]) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    matches = covers.get(chapter_range, [])
    if not matches:
        return None, warnings

    best = matches[0]
    tied = [item for item in matches if item.score == best.score]
    if len(tied) > 1:
        names = ", ".join(item.image_path.name for item in tied)
        warnings.append(f"multiple equally good covers found; used {best.image_path.name}; candidates: {names}")
    return best.image_path, warnings


def process_epubs(args: argparse.Namespace) -> list[ApplyResult]:
    ebooks_dir = Path(args.ebooks_dir)
    images_dir = Path(args.images_dir)
    covers = collect_cover_images(images_dir)
    characters = read_character_entries(Path(args.character_intro)) if args.character_intro else None
    results: list[ApplyResult] = []

    for epub_path in sorted(ebooks_dir.glob("*.epub")):
        chapter_range = extract_range(epub_path)
        if not chapter_range:
            results.append(ApplyResult(ChapterRange(0, 0), epub_path, status="skipped", warnings=["could not extract chapter range"]))
            continue

        cover_path, warnings = pick_cover(chapter_range, covers)
        result = ApplyResult(
            chapter_range=chapter_range,
            epub_path=epub_path,
            cover_path=cover_path,
            character_intro=characters is not None,
            warnings=warnings,
        )
        if not cover_path and not characters:
            result.status = "skipped"
            result.warnings.append("no matching cover image")
            results.append(result)
            continue
        if not cover_path:
            result.warnings.append("no matching cover image")

        if args.dry_run:
            result.status = "dry-run"
        else:
            result.backup_path = apply_front_matter(
                epub_path,
                cover_path=cover_path,
                characters=characters,
                backup=not args.no_backup,
            )
            result.status = "updated"
        results.append(result)

    return results


def print_report(results: list[ApplyResult]) -> None:
    print("| Range | EPUB | Cover | Characters | Status | Warnings |")
    print("|---|---|---|---|---|---|")
    for result in results:
        cover = result.cover_path.name if result.cover_path else "-"
        characters = "yes" if result.character_intro else "-"
        warnings = "; ".join(result.warnings) if result.warnings else "-"
        print(f"| {result.chapter_range.key} | {result.epub_path.name} | {cover} | {characters} | {result.status} | {warnings} |")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply range-named cover images to Mount Hua EPUB files.")
    parser.add_argument("--ebooks-dir", default="ebooks")
    parser.add_argument("--images-dir", default="images")
    parser.add_argument(
        "--character-intro",
        help="TSV file with columns: Thai character name, role/status, alias/nickname.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .epub.bak files before editing.")
    args = parser.parse_args()

    results = process_epubs(args)
    print_report(results)


if __name__ == "__main__":
    main()
