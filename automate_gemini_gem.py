import argparse
import subprocess
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


GEM_URL = "https://gemini.google.com/gem/6ec30f2e8afd"
DEFAULT_INPUT_DIR = "mount_hua_chapters_256_330"
DEFAULT_OUTPUT_DIR = "mount_hua_gemini_translated_256_330"
DEFAULT_PROFILE_DIR = ".gemini_browser_profile"


PROMPT_TEMPLATE = """{chapter_text}"""


def mac_clipboard_text():
    result = subprocess.run(
        ["pbpaste"], check=False, capture_output=True, text=True
    )
    return result.stdout.strip()


def set_mac_clipboard_text(text):
    subprocess.run(["pbcopy"], input=text, check=True, text=True)


def chapter_number(path):
    try:
        return int(path.name.split("__", 1)[0])
    except ValueError:
        return 0


def chapter_files(input_dir, start, end):
    files = sorted(Path(input_dir).glob("*.txt"), key=chapter_number)
    return [
        path
        for path in files
        if start <= chapter_number(path) <= end
    ]


def find_prompt_box(page):
    selectors = [
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"]',
        "rich-textarea div[contenteditable='true']",
        "textarea",
    ]

    for selector in selectors:
        locator = page.locator(selector).last
        try:
            locator.wait_for(state="visible", timeout=5000)
            return locator
        except PlaywrightTimeoutError:
            continue

    raise RuntimeError("Could not find Gemini prompt input box.")


def find_send_button(page):
    selectors = [
        'button[aria-label*="Send"]',
        'button[aria-label*="Submit"]',
        'button[data-testid*="send"]',
    ]

    for selector in selectors:
        button = page.locator(selector).last
        try:
            button.wait_for(state="visible", timeout=3000)
            return button
        except PlaywrightTimeoutError:
            continue

    return None


def clean_response_text(text):
    lines = []
    skip_lines = {
        "Mount Hua Translator • Custom Gem",
        "Mount Hua Translator",
        "Custom Gem",
    }

    for line in text.splitlines():
        stripped = line.strip()
        if stripped in skip_lines:
            continue
        lines.append(line.rstrip())

    return "\n".join(lines).strip()


def latest_response_text(page):
    candidates = page.evaluate(
        """
        () => {
            const selectors = [
                'model-response',
                'message-content',
                'response-container',
                '.response-container',
                '.model-response-text',
                '.markdown',
                '[class*="model-response"]',
                '[class*="response"]'
            ];

            const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && rect.width > 0
                    && rect.height > 0;
            };

            const nodes = Array.from(
                document.querySelectorAll(selectors.join(','))
            );

            const candidates = nodes
                .filter(visible)
                .map((element, index) => ({
                    index,
                    text: (element.innerText || element.textContent || '').trim()
                }))
                .filter((item) => item.text.length > 200);

            const thai = candidates.filter((item) => /[\\u0E00-\\u0E7F]/.test(item.text));
            return thai.length ? thai : candidates;
        }
        """
    )

    if not candidates:
        return ""

    return clean_response_text(candidates[-1]["text"])


def wait_for_response_to_finish(page, timeout_seconds, previous_response_text=""):
    deadline = time.time() + timeout_seconds
    last_text = ""
    stable_since = None

    while time.time() < deadline:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        text = latest_response_text(page)
        if previous_response_text and text == previous_response_text:
            time.sleep(2)
            continue

        if text and text == last_text:
            stable_since = stable_since or time.time()
            if time.time() - stable_since >= 8:
                return text
        else:
            last_text = text
            stable_since = None

        time.sleep(2)

    raise TimeoutError("Timed out waiting for Gemini response to finish.")


def copy_latest_response(page):
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    copy_buttons = page.locator(
        'button[aria-label*="Copy"], button[aria-label*="copy"], button[data-testid*="copy"]'
    )
    count = copy_buttons.count()
    if count == 0:
        raise RuntimeError("Could not find a Copy button for Gemini response.")

    copy_buttons.nth(count - 1).click()
    time.sleep(1)

    copied = mac_clipboard_text()
    if not copied:
        raise RuntimeError("Copy button did not put text on the clipboard.")

    return copied


def submit_prompt(page, prompt):
    prompt_box = find_prompt_box(page)
    prompt_box.click()
    set_mac_clipboard_text(prompt)
    page.keyboard.press("Meta+V")

    send_button = find_send_button(page)
    if send_button:
        send_button.click()
    else:
        page.keyboard.press("Meta+Enter")


def translate_chapters(args):
    input_paths = chapter_files(args.input_dir, args.start, args.end)
    if not input_paths:
        raise RuntimeError(f"No chapter files found in {args.input_dir}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=args.profile_dir,
            headless=False,
            viewport={"width": 1400, "height": 1000},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(args.gem_url, wait_until="domcontentloaded")

        print("\nBrowser opened.")
        print("Log in if needed, make sure the Gem chat is ready, then return here.")
        input("Press Enter to start sending chapters...")

        for input_path in input_paths:
            output_path = output_dir / input_path.name
            if output_path.exists() and output_path.stat().st_size > 0 and not args.force:
                print(f"Skipping existing output: {output_path}")
                continue

            try:
                chapter_text = input_path.read_text(encoding="utf-8").strip()
                prompt = PROMPT_TEMPLATE.format(chapter_text=chapter_text)

                print(f"Submitting {input_path.name}")
                previous_response_text = latest_response_text(page)
                submit_prompt(page, prompt)
                translated = wait_for_response_to_finish(
                    page, args.timeout, previous_response_text
                )

                if args.use_copy_button:
                    translated = copy_latest_response(page)

                output_path.write_text(translated + "\n", encoding="utf-8")
                print(f"Saved: {output_path}")

                if args.delay:
                    time.sleep(args.delay)
            except Exception as exc:
                print(f"Failed: {input_path.name}: {exc}")
                if not args.continue_on_error:
                    raise

        context.close()


def main():
    parser = argparse.ArgumentParser(
        description="Supervised Gemini Gem browser automation for chapter translation."
    )
    parser.add_argument("--gem-url", default=GEM_URL)
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile-dir", default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--start", type=int, default=256)
    parser.add_argument("--end", type=int, default=330)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--delay", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--use-copy-button",
        action="store_true",
        help="Use Gemini's Copy button instead of extracting text from the page.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue with the next chapter if one chapter fails or times out.",
    )
    args = parser.parse_args()

    translate_chapters(args)


if __name__ == "__main__":
    main()
