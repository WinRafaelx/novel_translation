# Mount Hua Scraping, Translation, and EPUB Tools

This folder contains scripts for:

1. Scraping SkyDemonOrder chapter links.
2. Downloading chapter text into `.txt` files.
3. Sending chapters to a Gemini Gem for translation through a supervised browser.
4. Building EPUB ebooks from translated `.txt` files.

Run commands from this project folder:

```bash
cd /Users/cielsensei/Raf_dev/tts_loo
```

## Setup

Use the project virtual environment if needed:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install cloudscraper requests beautifulsoup4 playwright ebooklib
python -m playwright install chromium
```

## 1. Scrape Chapter Links

Script: `tess.py`

Default command:

```bash
python tess.py
```

Output:

```text
mount_hua_links_clean.txt
```

This writes free chapter links only. To include paid/locked chapter links too:

```bash
python tess.py --include-paid --output mount_hua_all_links.txt
```

Use a different project URL:

```bash
python tess.py --url "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect" --output mount_hua_links_clean.txt
```

## 2. Scrape Chapter Text

Script: `scape_dynamic.py`

Scrape a chapter range from `mount_hua_links_clean.txt`:

```bash
python scape_dynamic.py --start 256 --end 330 --output-dir mount_hua_chapters_256_330
```

Inputs:

```text
mount_hua_links_clean.txt
```

Output folder:

```text
mount_hua_chapters_256_330/
```

Scrape one chapter URL:

```bash
python scape_dynamic.py --single "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect/256-what-opened-1"
```

Use a different links file:

```bash
python scape_dynamic.py --start 256 --end 330 --links mount_hua_all_links.txt --output-dir mount_hua_chapters_256_330
```

## 3. Translate With Gemini Gem

Script: `automate_gemini_gem.py`

This uses a visible Playwright browser. It does not bypass login or security checks. You log in manually, then the script submits chapters one by one.

Test one chapter first:

```bash
python automate_gemini_gem.py --start 256 --end 256 --force
```

When the browser opens:

1. Log in to Gemini if needed.
2. Confirm the Gem chat is ready.
3. Return to the terminal.
4. Press Enter to start.

Translate a full range:

```bash
python automate_gemini_gem.py --start 256 --end 330
```

Default input folder:

```text
mount_hua_chapters_256_330/
```

Default output folder:

```text
mount_hua_gemini_translated_256_330/
```

Use a custom input/output folder:

```bash
python automate_gemini_gem.py \
  --input-dir mount_hua_chapters_256_330 \
  --output-dir mount_hua_gemini_translated_256_330 \
  --start 256 \
  --end 330
```

Useful flags:

```bash
--force
```

Overwrite translated files that already exist.

```bash
--delay 10
```

Wait 10 seconds between chapters.

```bash
--timeout 900
```

Wait up to 900 seconds for each Gemini response.

```bash
--use-copy-button
```

Use Gemini's Copy button instead of extracting response text from the page. Usually leave this off.

Important: once the script starts submitting chapters, avoid touching or scrolling the Gemini browser window.

## 4. Make EPUB Books

Script: `make_epub_batches.py`

Preview planned EPUB groups:

```bash
python make_epub_batches.py --preview
```

Create EPUBs grouped by complete 10-episode ranges:

```bash
python make_epub_batches.py
```

Default input folder:

```text
mount_hua_gemini_translated_256_330/
```

Default output folder:

```text
ebooks/
```

Group by same title pattern:

```bash
python make_epub_batches.py --group-by title
```

Example: these files become one EPUB:

```text
0256__256_What_Opened_1.txt
0257__257_What_Opened_2.txt
0258__258_What_Opened_3.txt
0259__259_What_Opened_4.txt
0260__260_What_Opened_5.txt
```

Group by complete episode ranges, such as `301-310`.
Incomplete ranges are skipped:

```bash
python make_epub_batches.py --group-by range --group-size 10
```

Group by fixed size, such as 10 chapters per EPUB, without requiring complete
episode ranges:

```bash
python make_epub_batches.py --group-by size --group-size 10
```

Create EPUBs for a specific range:

```bash
python make_epub_batches.py --start 256 --end 330
```

Use custom folders:

```bash
python make_epub_batches.py \
  --input-dir mount_hua_gemini_translated_256_330 \
  --output-dir ebooks \
  --start 256 \
  --end 330
```

Set ebook metadata:

```bash
python make_epub_batches.py \
  --book-prefix "Return of the Mount Hua Sect" \
  --author "Gemini translation"
```

## 5. Generate Missing Covers With ChatGPT Project

Script: `automate_chatgpt_covers.py`

This uses a visible Playwright browser. It does not bypass login or security
checks. You log in manually, then the script checks `ebooks/`, skips EPUBs that
already have matching range-named cover images in `images/`, and loops until all
missing covers are saved.

Check which covers are missing:

```bash
python automate_chatgpt_covers.py --list-missing
```

Generate all missing covers:

```bash
python automate_chatgpt_covers.py --continue-on-error
```

When the browser opens:

1. Log in to ChatGPT if needed.
2. Confirm the Mount Hua Illustrator Project chat is ready.
3. Return to the terminal.
4. Press Enter to start.

Default input/output folders:

```text
ebooks/
images/
```

Generated cover files are named by chapter range so `apply_epub_covers.py` can
pick them up automatically:

```text
images/301-310.png
images/311-320.png
images/321-330.png
```

Useful flags:

```bash
--start 301 --end 330
```

Only process EPUBs whose chapter ranges overlap this range.

```bash
--force
```

Regenerate covers even when matching images already exist.

```bash
--max-passes 3
```

Stop after three full passes over missing covers. By default, the script keeps
looping until every EPUB has a matching cover.

After cover generation, apply covers to EPUBs:

```bash
python apply_epub_covers.py --dry-run
python apply_epub_covers.py
```

## Common Workflow

Run the full pipeline in this order:

```bash
python tess.py
python scape_dynamic.py --start 256 --end 330 --output-dir mount_hua_chapters_256_330
python automate_gemini_gem.py --start 256 --end 330
python make_epub_batches.py --preview
python make_epub_batches.py
python automate_chatgpt_covers.py --continue-on-error
python apply_epub_covers.py
```

## Output Summary

Chapter links:

```text
mount_hua_links_clean.txt
```

Raw scraped chapters:

```text
mount_hua_chapters_256_330/
```

Translated chapters:

```text
mount_hua_gemini_translated_256_330/
```

EPUB books:

```text
ebooks/
```

Cover images:

```text
images/
```
