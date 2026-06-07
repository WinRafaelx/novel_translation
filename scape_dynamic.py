import os
import re
import sys
import argparse
import requests
import cloudscraper
from bs4 import BeautifulSoup


DEFAULT_LINKS_FILE = "mount_hua_links_clean.txt"
DEFAULT_OUTPUT_DIR = "mount_hua_chapters"


def scrape_any_chapter(url, session=None):
    """Dynamically fetches and cleans chapter text from SkyDemonOrder."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        client = session or requests
        response = client.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the page: {e}")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # 1. Extract and sanitize Title dynamically
    title_element = soup.find("h1") or soup.select_one(".chapter-title, .title")
    title = (
        title_element.get_text(strip=True)
        if title_element
        else "Scraped_Chapter"
    )

    # 2. Isolate the main text container to reduce UI noise
    content_div = soup.find("article") or soup.select_one(
        ".chapter-content, .ep-content, .reader-content"
    )
    paragraphs = content_div.find_all("p") if content_div else soup.find_all("p")

    # Compiled regex patterns for fast dynamic UI matching
    ui_patterns = [
        re.compile(r"^prev$", re.IGNORECASE),
        re.compile(r"^next$", re.IGNORECASE),
        re.compile(r"^ch\.\s*\d+", re.IGNORECASE),  # Matches "Ch. 171", "Ch.173", etc.
        re.compile(r"^chapter\s*\d+\s*/\s*\d+", re.IGNORECASE),  # Matches "Chapter 172/1922"
        re.compile(r"tap.*text.*show.*hide.*control", re.IGNORECASE),
        re.compile(r"reading\s+settings", re.IGNORECASE),
    ]

    story_paragraphs = []

    for p in paragraphs:
        text = p.get_text(strip=True)

        if not text:
            continue

        # Dynamically drop paragraphs matching any UI control patterns
        if any(pattern.search(text) for pattern in ui_patterns):
            continue

        # Skip common site-wide navigation headers if leaked inside <p> elements
        if "return of the mount hua sect" in text.lower():
            continue

        story_paragraphs.append(text)

    return {"title": title, "content": "\n\n".join(story_paragraphs)}


def safe_filename(value):
    value = "".join(c for c in value if c.isalnum() or c in (" ", "_", "-")).rstrip()
    return re.sub(r"\s+", "_", value)


def load_chapter_links(path):
    chapter_pattern = re.compile(r"^Ch\.\s*(\d+)\s*-\s*(.*?):\s*(https?://\S+)\s*$")
    chapters = {}

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            match = chapter_pattern.match(line.strip())
            if not match:
                continue

            chapter_number = int(match.group(1))
            chapters[chapter_number] = {
                "title": match.group(2).strip(),
                "url": match.group(3).strip(),
            }

    return chapters


def save_chapter(chapter_number, result, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{chapter_number:04d}__{safe_filename(result['title'])}.txt"
    path = os.path.join(output_dir, filename)

    with open(path, "w", encoding="utf-8") as file:
        file.write(f"{result['title']}\n\n{result['content']}\n")

    return path


def scrape_chapter_range(start, end, links_file, output_dir):
    chapters = load_chapter_links(links_file)
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )

    saved = []
    failed = []

    for chapter_number in range(start, end + 1):
        chapter = chapters.get(chapter_number)
        if not chapter:
            print(f"Missing chapter {chapter_number} in {links_file}")
            failed.append(chapter_number)
            continue

        print(f"Scraping Ch. {chapter_number}: {chapter['url']}")
        result = scrape_any_chapter(chapter["url"], session=scraper)
        if not result or not result["content"].strip():
            print(f"Failed to scrape Ch. {chapter_number}")
            failed.append(chapter_number)
            continue

        path = save_chapter(chapter_number, result, output_dir)
        print(f"Saved: {path}")
        saved.append(path)

    print(f"Done. Saved {len(saved)} chapters to {output_dir}")
    if failed:
        print(f"Failed chapters: {', '.join(str(ch) for ch in failed)}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape SkyDemonOrder chapters into text files."
    )
    parser.add_argument("url", nargs="?", help="Single chapter URL to scrape.")
    parser.add_argument("--start", type=int, default=256, help="Start chapter number.")
    parser.add_argument("--end", type=int, default=330, help="End chapter number.")
    parser.add_argument(
        "--links", default=DEFAULT_LINKS_FILE, help="Chapter link list file."
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR, help="Folder for scraped chapters."
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Scrape only the provided URL instead of the chapter range.",
    )
    args = parser.parse_args()

    if args.single or args.url:
        target_url = args.url or (
            "https://skydemonorder.com/projects/"
            "3801994495-return-of-the-mount-hua-sect/"
            "1922-what-do-you-wish-for-2"
        )

        print(f"Scraping: {target_url} ...")
        result = scrape_any_chapter(target_url)

        if result:
            filename = f"{safe_filename(result['title'])}.txt"

            with open(filename, "w", encoding="utf-8") as file:
                file.write(f"{result['title']}\n\n{result['content']}\n")

            print(f"Success! Clean text saved to: {filename}")
        return

    scrape_chapter_range(args.start, args.end, args.links, args.output_dir)


if __name__ == "__main__":
    main()
