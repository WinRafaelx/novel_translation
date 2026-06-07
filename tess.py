import argparse
import json
import re
from html import unescape

import cloudscraper
from bs4 import BeautifulSoup


PROJECT_URL = (
    "https://skydemonorder.com/projects/"
    "3801994495-return-of-the-mount-hua-sect"
)
LIVEWIRE_UPDATE_URL = "https://skydemonorder.com/livewire-0c52561f/update"
OUTPUT_FILENAME = "mount_hua_links_clean.txt"


def make_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


def fetch_project_page(scraper, project_url):
    response = scraper.get(project_url, timeout=30)
    response.raise_for_status()
    return response.text


def load_chapter_list_html(scraper, project_url, project_html):
    soup = BeautifulSoup(project_html, "html.parser")

    csrf_tag = soup.select_one('meta[name="csrf-token"]')
    component = soup.find(attrs={"wire:name": "project.chapter-list"})

    if not csrf_tag or not component:
        raise RuntimeError("Could not find the Livewire chapter-list component.")

    lazy_call = component.get("x-intersect", "")
    lazy_match = re.search(r"__lazyLoad\('([^']+)'\)", lazy_call)
    if not lazy_match:
        raise RuntimeError("Could not find the Livewire lazy-load payload.")

    csrf_token = csrf_tag["content"]
    payload = {
        "_token": csrf_token,
        "components": [
            {
                "snapshot": component["wire:snapshot"],
                "updates": {},
                "calls": [
                    {
                        "path": "",
                        "method": "__lazyLoad",
                        "params": [lazy_match.group(1)],
                    }
                ],
            }
        ],
    }
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": project_url,
        "X-CSRF-TOKEN": csrf_token,
        "X-Livewire": "",
    }

    response = scraper.post(
        LIVEWIRE_UPDATE_URL, headers=headers, json=payload, timeout=30
    )
    response.raise_for_status()

    data = response.json()
    return data["components"][0]["effects"]["html"]


def decode_js_string(value):
    return json.loads(f'"{value}"')


def extract_chapters(chapter_list_html, include_paid=False):
    groups = ["freeChapters"]
    if include_paid:
        groups.append("paidChapters")

    chapters = []
    seen_slugs = set()

    for group in groups:
        match = re.search(
            rf"{group}: JSON\.parse\('((?:\\'|[^'])*)'\)",
            chapter_list_html,
        )
        if not match:
            continue

        for chapter in json.loads(decode_js_string(match.group(1))):
            slug = chapter.get("slug")
            if not slug or slug in seen_slugs:
                continue

            seen_slugs.add(slug)
            chapters.append(chapter)

    if not chapters:
        raise RuntimeError("No chapter arrays found in the Livewire response.")

    return sorted(chapters, key=lambda item: int(item.get("episode", 0)))


def build_chapter_url(project_url, slug):
    return f"{project_url.rstrip('/')}/{slug}"


def write_chapter_links(chapters, project_url, output_filename):
    with open(output_filename, "w", encoding="utf-8") as file:
        for chapter in chapters:
            episode = chapter.get("episode", "")
            title = unescape(chapter.get("title", "")).strip()
            url = build_chapter_url(project_url, chapter["slug"])
            file.write(f"Ch. {episode} - {title}: {url}\n")


def fetch_chapter_links(
    project_url=PROJECT_URL,
    output_filename=OUTPUT_FILENAME,
    include_paid=False,
):
    scraper = make_scraper()

    print(f"Fetching project page: {project_url}")
    project_html = fetch_project_page(scraper, project_url)

    print("Loading Livewire chapter list...")
    chapter_list_html = load_chapter_list_html(scraper, project_url, project_html)

    chapters = extract_chapters(chapter_list_html, include_paid=include_paid)
    write_chapter_links(chapters, project_url, output_filename)

    print(f"Success! Wrote {len(chapters)} chapter links to: {output_filename}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Return of the Mount Hua Sect chapter links."
    )
    parser.add_argument("--url", default=PROJECT_URL, help="Project page URL.")
    parser.add_argument(
        "--output", default=OUTPUT_FILENAME, help="Output text file path."
    )
    parser.add_argument(
        "--include-paid",
        action="store_true",
        help="Also include paid/locked chapter links from the chapter list.",
    )
    args = parser.parse_args()

    fetch_chapter_links(
        project_url=args.url,
        output_filename=args.output,
        include_paid=args.include_paid,
    )


if __name__ == "__main__":
    main()
