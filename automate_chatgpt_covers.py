import argparse
import base64
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


PROJECT_URL = "https://chatgpt.com/g/g-p-6a1bbe64b7d88191becf9f44640b7314-mount-hua-illustrator/project"
DEFAULT_EBOOKS_DIR = "ebooks"
DEFAULT_IMAGES_DIR = "images"
DEFAULT_PROFILE_DIR = ".chatgpt_browser_profile"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


PROMPT_TEMPLATE = """Read the attached EPUB and create a cover image generation prompt for this volume.

Infer the most important cover scene, characters, conflict, setting, mood, and visual symbols from the EPUB.

Return only one polished image prompt suitable for a vertical ebook cover.

Prompt requirements:
- Vertical ebook cover composition, 2:3 aspect ratio.
- Wuxia/xianxia martial arts novel style.
- Cinematic painted illustration, dramatic lighting, clear focal character or scene.
- Use Mount Hua/plum blossom imagery only if it fits this volume.
- No readable text, no logos, no watermarks, no typography.
- Do not generate the image yet.

Volume: {volume_name}
Chapter range: {chapter_range}
"""

GENERATE_PROMPT = """Start generating the ebook cover image now. Follow the image prompt in your last response exactly. No readable text, no logos, no watermarks."""


@dataclass(frozen=True)
class EbookTask:
    epub_path: Path
    start: int
    end: int

    @property
    def key(self) -> str:
        return f"{self.start}-{self.end}"


def set_mac_clipboard_text(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, check=True, text=True)


def extract_range(path: Path) -> tuple[int, int] | None:
    match = re.search(r"(?<!\d)(\d{3,4})\D+(\d{3,4})(?!\d)", path.stem)
    if not match:
        return None
    start, end = (int(value) for value in match.groups())
    if start > end:
        return None
    return start, end


def existing_cover_for(images_dir: Path, key: str) -> Path | None:
    exact_stems = {key, key.replace("-", "_"), f"cover-{key}", f"cover_{key.replace('-', '_')}"}
    for image_path in sorted(images_dir.iterdir() if images_dir.exists() else []):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if image_path.stem.lower() in exact_stems:
            return image_path
    return None


def collect_missing_tasks(args: argparse.Namespace) -> list[EbookTask]:
    ebooks_dir = Path(args.ebooks_dir)
    images_dir = Path(args.images_dir)
    tasks: list[EbookTask] = []

    for epub_path in sorted(ebooks_dir.glob("*.epub")):
        chapter_range = extract_range(epub_path)
        if not chapter_range:
            print(f"Skipping EPUB with no chapter range: {epub_path.name}")
            continue

        start, end = chapter_range
        if args.start is not None and end < args.start:
            continue
        if args.end is not None and start > args.end:
            continue

        key = f"{start}-{end}"
        if existing_cover_for(images_dir, key) and not args.force:
            continue
        tasks.append(EbookTask(epub_path=epub_path, start=start, end=end))

    return tasks


def find_prompt_box(page):
    selectors = [
        'div[contenteditable="true"][role="textbox"]',
        'div.ProseMirror[contenteditable="true"]',
        'div[contenteditable="true"]',
        "textarea",
    ]
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            locator.wait_for(state="visible", timeout=5000)
            return locator
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError("Could not find ChatGPT prompt input box.")


def find_send_button(page):
    selectors = [
        'button[data-testid="send-button"]',
        'button[aria-label*="Send"]',
        'button[aria-label*="send"]',
        'button[type="submit"]',
    ]
    for selector in selectors:
        button = page.locator(selector).last
        try:
            button.wait_for(state="visible", timeout=2000)
            return button
        except PlaywrightTimeoutError:
            continue
    return None


def assistant_messages(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
            const selectors = [
                '[data-message-author-role="assistant"]',
                '.markdown',
                '[class*="markdown"]'
            ];

            const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && rect.width > 0
                    && rect.height > 0;
            };

            return Array.from(document.querySelectorAll(selectors.join(',')))
                .filter(visible)
                .map((element, index) => ({
                    index,
                    text: (element.innerText || element.textContent || '').trim()
                }))
                .filter((item) => item.text.length >= 80)
                .sort((a, b) => a.index - b.index);
        }
        """
    )


def latest_response_text(page) -> str:
    candidates = assistant_messages(page)
    return candidates[-1]["text"] if candidates else ""


def is_chatgpt_generating(page) -> bool:
    return page.evaluate(
        """
        () => {
            const buttons = Array.from(document.querySelectorAll('button'));
            return buttons.some((button) => {
                const label = [
                    button.getAttribute('aria-label') || '',
                    button.getAttribute('data-testid') || '',
                    button.innerText || '',
                    button.textContent || '',
                ].join(' ').toLowerCase();
                return label.includes('stop')
                    || label.includes('streaming')
                    || label.includes('cancel');
            });
        }
        """
    )


def wait_for_response_to_finish(
    page,
    timeout_seconds: int,
    previous_count: int = 0,
    previous_response_text: str = "",
) -> str:
    deadline = time.time() + timeout_seconds
    last_text = ""
    stable_since = None

    while time.time() < deadline:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        messages = assistant_messages(page)
        if len(messages) <= previous_count:
            time.sleep(2)
            continue

        text = messages[-1]["text"]
        if previous_response_text and text == previous_response_text:
            time.sleep(2)
            continue

        if text and text == last_text:
            stable_since = stable_since or time.time()
            if time.time() - stable_since >= 10 and not is_chatgpt_generating(page):
                return text
        else:
            last_text = text
            stable_since = None

        time.sleep(2)

    raise TimeoutError("Timed out waiting for ChatGPT text response.")


def wait_for_upload_input(page):
    selectors = [
        'input[type="file"]',
        'form input[type="file"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            locator.wait_for(state="attached", timeout=5000)
            return locator
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError("Could not find ChatGPT file upload input.")


def click_attach_button_if_needed(page) -> None:
    selectors = [
        'button[aria-label*="Attach"]',
        'button[aria-label*="Upload"]',
        'button[data-testid*="attach"]',
        'button[data-testid*="upload"]',
    ]
    for selector in selectors:
        button = page.locator(selector).last
        try:
            button.wait_for(state="visible", timeout=1000)
            button.click()
            time.sleep(1)
            return
        except PlaywrightTimeoutError:
            continue


def upload_epub(page, epub_path: Path) -> None:
    try:
        upload_input = wait_for_upload_input(page)
    except RuntimeError:
        click_attach_button_if_needed(page)
        upload_input = wait_for_upload_input(page)
    upload_input.set_input_files(str(epub_path))


def candidate_images(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
            const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && rect.width >= 256
                    && rect.height >= 256;
            };

            return Array.from(document.images)
                .map((img, index) => {
                    const rect = img.getBoundingClientRect();
                    return {
                        index,
                        src: img.currentSrc || img.src || '',
                        alt: img.alt || '',
                        width: img.naturalWidth || Math.round(rect.width),
                        height: img.naturalHeight || Math.round(rect.height),
                        area: (img.naturalWidth || rect.width) * (img.naturalHeight || rect.height),
                        visible: visible(img),
                    };
                })
                .filter((item) => item.visible && item.src && item.area >= 262144)
                .sort((a, b) => a.index - b.index);
        }
        """
    )


def wait_for_new_image(page, previous_count: int, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    last_count = previous_count
    stable_since = None

    while time.time() < deadline:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        images = candidate_images(page)
        if len(images) > last_count:
            last_count = len(images)
            stable_since = time.time()
        elif len(images) > previous_count and stable_since and time.time() - stable_since >= 15:
            return images[-1]
        time.sleep(3)

    raise TimeoutError("Timed out waiting for a generated image.")


def submit_text_prompt(page, prompt: str) -> None:
    prompt_box = find_prompt_box(page)
    prompt_box.click()
    set_mac_clipboard_text(prompt)
    page.keyboard.press("Meta+V")

    send_button = find_send_button(page)
    if send_button:
        send_button.click()
    else:
        page.keyboard.press("Meta+Enter")


def extension_for(content_type: str, data: bytes) -> str:
    content_type = content_type.lower().split(";", 1)[0].strip()
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/webp":
        return ".webp"
    if content_type == "image/png":
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ".webp"
    return ".png"


def fetch_image_bytes(page, image: dict) -> tuple[bytes, str]:
    src = image["src"]
    if src.startswith("data:"):
        header, payload = src.split(",", 1)
        content_type = header.split(";", 1)[0].removeprefix("data:")
        data = base64.b64decode(payload)
        return data, extension_for(content_type, data)

    if src.startswith("blob:"):
        result = page.evaluate(
            """
            async (src) => {
                const response = await fetch(src);
                const contentType = response.headers.get('content-type') || '';
                const buffer = await response.arrayBuffer();
                const bytes = Array.from(new Uint8Array(buffer));
                return {contentType, bytes};
            }
            """,
            src,
        )
        data = bytes(result["bytes"])
        return data, extension_for(result.get("contentType", ""), data)

    response = page.context.request.get(src, timeout=60000)
    if not response.ok:
        raise RuntimeError(f"Image request failed with HTTP {response.status}: {src}")
    data = response.body()
    return data, extension_for(response.headers.get("content-type", ""), data)


def submit_cover_request(page, task: EbookTask, timeout_seconds: int) -> dict:
    before_count = len(candidate_images(page))
    upload_epub(page, task.epub_path)
    time.sleep(4)

    prompt = PROMPT_TEMPLATE.format(
        volume_name=task.epub_path.stem.replace("_", " "),
        chapter_range=task.key,
    )
    previous_messages = assistant_messages(page)
    previous_count = len(previous_messages)
    previous_response_text = latest_response_text(page)
    submit_text_prompt(page, prompt)
    cover_prompt = wait_for_response_to_finish(
        page,
        timeout_seconds,
        previous_count=previous_count,
        previous_response_text=previous_response_text,
    )
    print(f"Prompt ready for {task.key}: {cover_prompt[:160].replace(chr(10), ' ')}...")

    submit_text_prompt(page, GENERATE_PROMPT)
    return wait_for_new_image(page, before_count, timeout_seconds)


def save_cover(page, image: dict, output_path_without_suffix: Path) -> Path:
    data, suffix = fetch_image_bytes(page, image)
    output_path = output_path_without_suffix.with_suffix(suffix)
    output_path.write_bytes(data)
    return output_path


def generate_covers(args: argparse.Namespace) -> None:
    images_dir = Path(args.images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=False,
            accept_downloads=True,
            viewport={"width": 1400, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(args.project_url, wait_until="domcontentloaded")

        print("\nBrowser opened.")
        print("Log in if needed and make sure the ChatGPT Project chat is ready.")
        input("Press Enter to start generating missing covers...")

        pass_number = 0
        while True:
            pass_number += 1
            tasks = collect_missing_tasks(args)
            if not tasks:
                print("All EPUBs already have matching covers.")
                break

            print(f"\nPass {pass_number}: {len(tasks)} cover(s) missing.")
            for task in tasks:
                output_base = images_dir / task.key
                try:
                    print(f"Submitting {task.epub_path.name} -> {output_base.name}.*")
                    image = submit_cover_request(page, task, args.timeout)
                    output_path = save_cover(page, image, output_base)
                    print(f"Saved: {output_path}")
                    if args.delay:
                        time.sleep(args.delay)
                except Exception as exc:
                    print(f"Failed: {task.epub_path.name}: {exc}")
                    if not args.continue_on_error:
                        raise

            remaining = collect_missing_tasks(args)
            if not remaining:
                print("\nAll covers generated.")
                break
            if args.max_passes and pass_number >= args.max_passes:
                names = ", ".join(task.key for task in remaining)
                raise RuntimeError(f"Missing covers after {pass_number} pass(es): {names}")

            print("Some covers are still missing; starting another pass.")

        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate missing EPUB cover images through a supervised ChatGPT Project browser."
    )
    parser.add_argument("--project-url", default=PROJECT_URL)
    parser.add_argument("--ebooks-dir", default=DEFAULT_EBOOKS_DIR)
    parser.add_argument("--images-dir", default=DEFAULT_IMAGES_DIR)
    parser.add_argument("--profile-dir", default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--delay", type=int, default=5)
    parser.add_argument(
        "--max-passes",
        type=int,
        default=0,
        help="Maximum full passes over missing EPUBs. 0 means keep looping until complete.",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate covers even if matching images already exist.")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue looping if an EPUB fails; useful when ChatGPT rate limits one request.",
    )
    parser.add_argument("--list-missing", action="store_true", help="Only print missing covers; do not open ChatGPT.")
    args = parser.parse_args()

    if args.list_missing:
        tasks = collect_missing_tasks(args)
        if not tasks:
            print("All EPUBs already have matching covers.")
            return
        for task in tasks:
            print(f"{task.key}: {task.epub_path}")
        return

    generate_covers(args)


if __name__ == "__main__":
    main()
