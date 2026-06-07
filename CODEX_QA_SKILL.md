# Codex Thai Novel QA Skill

This project uses a custom Codex skill to perform the human-quality QA and polishing step after raw Gemini translation.

The skill is designed for Thai web-novel translation, especially wuxia / martial-arts prose where pronouns, hierarchy, insults, rhythm, and title/register choices strongly affect readability.

## Role In The Pipeline

```text
novel_gemini_translated/
  Raw Gemini output
        |
        v
novel_final/
  Working files for Codex QA and polishing
        |
        v
Codex Thai Novel QA Skill
  critique, line edit, heading cleanup, pronoun/register QA, prose compacting
        |
        v
verified EPUB source
```

The main pipeline calls Codex after copying translated files into `novel_final/`.

Example command from `novel_pipeline.py`:

```text
$thai-novel-translation-pipeline chapter 820 to 825 auto apply.
Use English source files from `novel_chapters` and Thai files from `novel_final`.
Edit only files in `novel_final` for this chapter range.
```

## What The Skill Checks

The QA skill reviews the Thai translation against the English source and looks for:

- Mistranslations or missing meaning.
- Missing subjects, objects, speakers, or action continuity.
- Wrong names, sect names, martial arts terms, titles, or honorifics.
- Source-language leaks such as English, romanization, Chinese, Japanese, or Korean text.
- Machine-output artifacts, footnote leftovers, translator notes, and malformed text.
- Modern or inappropriate Thai pronouns such as `คุณ`, `นาย`, `เธอ`, or `หล่อน`.
- Register problems where rank, intimacy, hostility, or respect is wrong.
- Over-expanded or machine-like prose that weakens pacing.
- Chapter headings that are missing, malformed, or still contain English title text.

## Heading Cleanup

Gemini sometimes omits chapter headings. The Python pipeline can generate a fallback heading from the filename:

```text
ตอนที่ 821 - I Won This War (1)
```

The Codex QA skill then translates only the title portion while preserving the chapter number and part marker:

```text
ตอนที่ 821 - ศึกนี้ข้าชนะแล้ว (1)
```

The skill should not rewrite the whole heading structure unless the chapter number or part marker is wrong.

## Pronoun And Register Rules

Thai pronouns carry hierarchy, intimacy, contempt, and genre tone. The skill treats pronoun/register QA as a core translation-quality issue, not optional polish.

General guidance:

- `คุณ` is usually too modern or neutral-polite for wuxia dialogue.
- Juniors addressing elders, sect leaders, abbots, or respected figures usually need `ท่าน`, a title, or name-title.
- Hostile narration or dialogue may correctly use `มัน`, `แก`, `เจ้า`, or insults.
- Deliberate contempt from characters such as Chung Myung should be preserved when it carries comedy or force.
- Formal speakers should not randomly shift into modern casual pronouns.
- Repeated `เขา` should be clarified with names, titles, `อีกฝ่าย`, or `คนผู้นั้น` when actor identity becomes unclear.

The skill avoids global pronoun replacements. Each suspicious line is checked in context before editing.

## Prose Polishing Rules

The skill improves readability without flattening the novel's energy.

It may compact paragraphs when they are:

- Repetitive.
- Machine-like.
- Overly long without adding emotion or action.
- Slowed down by filler phrasing.

It preserves:

- Jokes and insults.
- Martial-arts impact words.
- Character voice.
- Emotional beats.
- Crowd reactions.
- Action clarity.
- Genre flavor and intensity.

## Edit Strategy

The skill uses a bounded pass system:

1. Pass 1: fix artifacts, wrong meaning, broken Thai, headings, obvious pronoun/register issues, and the worst bloated prose.
2. Pass 2: re-read changed snippets, catch side effects, and fix remaining concrete issues.
3. Pass 3: only address remaining high/medium issues. Avoid broad stylistic rewriting.

The run stops early when:

- No high or medium issues remain.
- The latest pass produces no meaningful edits.
- Only low-value style preferences remain.
- Further compaction would weaken voice, jokes, emotion, or action.

## Verification Patterns

The skill and pipeline use targeted scans such as:

```bash
rg -n "[A-Za-z]|[一-龯ぁ-んァ-ン가-힣]" novel_final
rg -n "คุณ|พวกคุณ|นาย|พวกนาย|เธอ|หล่อน" novel_final
rg -n "PR/N|Reports|Provincial|Muscle Memory" novel_final
```

The Python pipeline also emits a verification report:

```text
pipeline_reports/0820_0825_verification.md
```

## Example QA Outcome

Before:

```text
ตอนที่ 821 - I Won This War (1)
```

After:

```text
ตอนที่ 821 - ศึกนี้ข้าชนะแล้ว (1)
```

Before:

```text
คุณคิดว่าพวกคุณจะรอดไปได้หรือ
```

After, depending on speaker/listener context:

```text
เจ้าคิดว่าพวกเจ้าจะรอดไปได้หรือ
```

or:

```text
ท่านคิดว่าพวกท่านจะรอดไปได้หรือ
```

The skill chooses based on hierarchy, tone, and scene intent.

## Why This Matters

Raw machine translation can produce readable Thai but often misses genre-sensitive details:

- Who is above or below whom.
- Whether a line is respectful, hostile, comic, or arrogant.
- Whether a title should sound martial-arts-native rather than literal.
- Whether prose has become too bloated or too flat.

The Codex QA skill closes that gap by combining source comparison, Thai line editing, and domain-specific translation rules before EPUB publishing.
