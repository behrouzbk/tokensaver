# tokensaver

**Find out what your prompt costs on every major AI model, and exactly which changes make it cheaper.**

[![CI](https://github.com/behrouzbk/tokensaver/actions/workflows/ci.yml/badge.svg)](https://github.com/behrouzbk/tokensaver/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/prompt-tokensaver.svg)](https://pypi.org/project/prompt-tokensaver/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/behrouzbk/tokensaver/blob/main/LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

Most token counters stop at a number. tokensaver tells you **what to change**: every
suggestion comes with a reason, the tokens it saves, and what that is worth in dollars.
It runs 100% offline. Your prompt never leaves your machine.

![tokensaver optimize: each suggestion with its token and dollar savings, a diff, and the total](https://cdn.jsdelivr.net/gh/behrouzbk/tokensaver@main/assets/demo.svg)

## 🌍 Works in every language

**tokensaver works with prompts in any language and any script.** Token counting, cost
comparison, JSON minification, whitespace cleanup and duplicate detection are
**tested in CI on 55 languages** on every commit
([see the test](https://github.com/behrouzbk/tokensaver/blob/main/tests/test_languages.py)):

Arabic · Bengali · Bulgarian · Burmese (Myanmar) · Chinese (Simplified) · Chinese
(Traditional, Hong Kong) · Chinese (Traditional, Macau) · Chinese (Traditional, Taiwan) ·
Croatian · Czech · Danish · Dutch · English · Estonian · Finnish · French · German · Greek ·
Hebrew · Hindi · Hungarian · Indonesian · Italian · Japanese · Kannada · Khmer · Korean ·
Lithuanian · Malay · Malayalam · Marathi · Nepali · Nigerian Pidgin · Norwegian · Persian
(Farsi) · Polish · Portuguese (Brazil) · Portuguese (Portugal) · Punjabi (Gurmukhi) ·
Romanian · Russian · Serbian (Cyrillic) · Slovak · Slovenian · Spanish · Swahili · Swedish ·
Tagalog (Filipino) · Tamil · Telugu · Thai · Turkish · Ukrainian · Urdu · Vietnamese

Right-to-left scripts (Arabic, Hebrew, Persian, Urdu) and languages without spaces between
words (Chinese, Japanese, Thai, Khmer, Burmese) included. The `filler` rule understands
English and Persian; `repeated-instructions` and "Example 1:" detection, only English.
**Native speakers: add your language's filler phrases in
[#5](https://github.com/behrouzbk/tokensaver/issues/5).**

## Before / after

`examples/messy_prompt.txt` is a typical customer-support system prompt: polite filler, a
rule written twice, a paragraph pasted twice, and pretty-printed JSON.

```text
$ tokensaver optimize examples/messy_prompt.txt --apply all

  #  Suggestion                                                    Tokens  $/1k calls  Status
  1  Minify JSON block (140 chars, was 185)  line 13                  -18     $0.0450  applied
  2  Minify JSON block (200 chars, was 392)  line 39                  -43     $0.1075  applied
  3  Duplicate line: “- Never share internal information…”  line 30   -12     $0.0300  applied
  4  Duplicate paragraph: “Please note that you must only…”  line 34  -41     $0.1025  applied
  5  Repeated instruction: “Make sure you keep the answer…”  line 32  -12     $0.0300  applied
  7  Filler: “I would like you to…” (×1)  line 4                      -6     $0.0150  applied
 ...
 15  Long example (~198 tokens)  line 60                             ≤198     $0.4950  flag

╭──────────────────────── Total savings on gpt-4o ─────────────────────────╮
│ Before: 834 tokens                                                       │
│ After:  665 tokens                                                       │
│ Saved:  169 tokens (20.3%) = $0.000423 per call, $0.4225 per 1,000 calls, │
│ $422.50 per 1M calls                                                     │
╰──────────────────────────────────────────────────────────────────────────╯
```

What changed in the prompt:

```diff
-I would like you to please read the customer's message carefully and answer their question.
-As an AI language model, you should always be polite, friendly and professional.
+Read the customer's message carefully and answer their question.
+You should always be polite, friendly and professional.
...
-{
-    "answer": "string",
-    "category": "billing | technical | account | other",
-    ...
-}
+{"answer":"string","category":"billing | technical | account | other","confidence":0.0,...}
...
-- Never share internal information, discount codes or employee names.
-- Make sure you keep the answer under 120 words.
```

With only the default **safe** rules (no wording changes at all), the same prompt drops from
834 to 772 tokens. tokensaver then tells you that the review suggestions would save
107 more, so you decide.

## Install

```bash
pip install prompt-tokensaver
```

The command is `tokensaver`. Requires Python 3.10 or newer. Works on Windows, macOS and
Linux.

## Quick start (2 minutes)

```bash
# 1. How many tokens, and what does one call cost?
tokensaver count prompt.txt --model gpt-4o
tokensaver count "Summarize this article in three bullet points."

# 2. Which model is cheapest for this prompt?
tokensaver compare prompt.txt
tokensaver compare prompt.txt --models gpt-4o,claude-sonnet-5-5,gemini-2.5-flash

# 3. What should I change? (safe changes are applied, others are suggested)
tokensaver optimize prompt.txt

# 4. Apply everything you agree with and save a copy (the original is never overwritten)
tokensaver optimize prompt.txt --apply all --output prompt.optimized.txt
tokensaver optimize prompt.txt --apply json,whitespace,filler -o prompt.optimized.txt

# Pipe text in with "-", list models and prices
cat prompt.txt | tokensaver count -        # PowerShell: Get-Content prompt.txt | tokensaver count -
tokensaver models
```

Windows paths work as usual: `tokensaver optimize examples\messy_prompt.txt`.

## Commands and options

Run `tokensaver <command> --help` for the same information in your terminal.

### Input (every command)

`INPUT` can be any of:

| You pass | tokensaver reads |
|---|---|
| `prompt.txt` or `C:\prompts\system.md` | the file (UTF-8; a byte-order mark is ignored) |
| `-` | text piped in on stdin |
| `"Summarize this in 3 bullets."` | the text itself |

A mistyped file name like `promt.txt` is an error, not silently counted as text.

### `tokensaver count INPUT`

Token count and input cost on one model.

| Option | What it does |
|---|---|
| `--model`, `-m` | Model to price against. Default: `gpt-4o`. See `tokensaver models` for all names. |
| `--prices FILE` | Use your own `prices.json` instead of the bundled one. |

### `tokensaver compare INPUT`

Tokens and input cost on many models, cheapest first.

| Option | What it does |
|---|---|
| `--models a,b,c` | Only these models (comma-separated). Default: all of them. |
| `--prices FILE` | Use your own `prices.json`. |

### `tokensaver optimize INPUT`

Suggestions with the tokens and dollars each one saves, a before/after diff and the
total.

| Option | What it does |
|---|---|
| `--model`, `-m` | Model to measure savings on. Default: `gpt-4o`. |
| `--apply safe` | **Default.** Applies only the safe rules (`json`, `whitespace`). Review rules are listed with their savings but not applied. |
| `--apply all` | Applies every rule. Read the suggestions first. |
| `--apply none` | Applies nothing; just shows the suggestions. |
| `--apply json,duplicates` | Applies only the rules you list. Names: `json`, `whitespace`, `duplicates`, `repeated-instructions`, `filler`, `long-examples`. |
| `--output FILE`, `-o FILE` | Saves the optimized prompt to `FILE`. Without it, nothing is written. The input file is **never** overwritten. |
| `--force` | Lets `--output` replace a file that already exists. It still refuses to overwrite the input file. |
| `--no-diff` | Hides the before/after diff (it is shown by default). |
| `--prices FILE` | Use your own `prices.json`. |

Common combinations:

```bash
tokensaver optimize prompt.txt                                   # look first: safe fixes only, nothing saved
tokensaver optimize prompt.txt --apply all -o prompt.min.txt     # apply everything, save a copy
tokensaver optimize prompt.txt --apply json,whitespace,duplicates -o prompt.min.txt
tokensaver optimize prompt.txt -m claude-sonnet-5-5 --no-diff    # savings on Claude, short output
tokensaver optimize prompt.txt --apply all -o prompt.min.txt --force   # re-run and replace the copy
```

### `tokensaver models` and `tokensaver version`

`models` lists every supported model with its prices and whether counts are exact.
`version` prints the installed version.

## Optimizer rules

Each rule is a small module in [`src/tokensaver/optimizer/`](https://github.com/behrouzbk/tokensaver/tree/main/src/tokensaver/optimizer).
**Safe** rules cannot change meaning and are applied by default. **Review** rules are shown
with their savings and applied only when you ask (`--apply all` or `--apply <rule,...>`).
Code blocks are never changed. Few-shot examples are never reworded.

| Rule | Risk | What it does |
|---|---|---|
| `json` | safe | Minifies pretty-printed JSON. Only whitespace outside strings is removed; the result is re-parsed and compared, so keys, values and number formats stay exactly the same. |
| `whitespace` | safe | Removes trailing spaces, extra blank lines and blank lines at the start and end. Indentation and spaces inside lines are kept. |
| `duplicates` | review | Finds duplicate lines and duplicate or near-duplicate (≥90% similar) paragraphs. |
| `repeated-instructions` | review | Finds the same instruction given twice in different words, such as "Always respond in JSON" and "Remember to always respond in JSON". |
| `filler` | review | Removes polite filler ("I would like you to please…", "As an AI language model…", "Thanks in advance!") and shortens wordy phrases ("in order to" → "to"). |
| `long-examples` | review | Flags few-shot examples over ~150 tokens and prompts with more than 3 examples. Only flags them; it never edits. |

Every saving is **measured**: tokensaver counts the prompt before and after each change on
the model you chose. Changes that save nothing on that model are not listed. (Safe
whitespace fixes that save 0 tokens are still applied for a tidy file, and reported in one
line.)

## Supported models

Prices are USD per 1M tokens, standard tier, as of **2026-10-26**. They live in
[`src/tokensaver/data/prices.json`](https://github.com/behrouzbk/tokensaver/blob/main/src/tokensaver/data/prices.json) with a source URL for
each model. Edit that file, or pass your own with `--prices my_prices.json`.

| Model | Provider | Input / 1M | Output / 1M | Token count |
|---|---|---:|---:|---|
| gpt-6-astra | OpenAI | $10.00 | $50.00 | estimated |
| gpt-6.1-sol | OpenAI | $2.00 | $10.00 | estimated |
| gpt-6-luna | OpenAI | $0.10 | $0.50 | estimated |
| gpt-5.5 | OpenAI | $5.00 | $30.00 | **exact** |
| gpt-5.4-mini | OpenAI | $0.75 | $4.50 | **exact** |
| gpt-5-mini | OpenAI | $0.25 | $2.00 | **exact** |
| gpt-4.1 | OpenAI | $2.00 | $8.00 | **exact** |
| gpt-4.1-mini | OpenAI | $0.40 | $1.60 | **exact** |
| gpt-4o | OpenAI | $2.50 | $10.00 | **exact** |
| gpt-4o-mini | OpenAI | $0.15 | $0.60 | **exact** |
| claude-fable-5-1 | Anthropic | $10.00 | $50.00 | estimated |
| claude-opus-5-5 | Anthropic | $4.00 | $20.00 | estimated |
| claude-sonnet-5-5 | Anthropic | $2.00 | $10.00 | estimated |
| claude-haiku-5-5 | Anthropic | $0.10 | $0.50 | estimated |
| claude-haiku-4-5 | Anthropic | $1.00 | $5.00 | estimated |
| gemini-4-argon | Google | $2.00 | $10.00 | estimated |
| gemini-3.8-flash | Google | $0.75 | $3.75 | estimated |
| gemini-3.1-pro-preview | Google | $2.00 | $12.00 | estimated |
| gemini-2.5-flash | Google | $0.30 | $2.50 | estimated |
| gemini-2.5-flash-lite | Google | $0.10 | $0.40 | estimated |

Run `tokensaver models` to see the list for your installed version.

## Limitations

Please read this before relying on the numbers.

- **Exact vs estimated.** Counts are exact only for OpenAI models that `tiktoken` maps to a
  tokenizer (shown as "exact"). Claude, Gemini and GPT-6 have no offline tokenizer, so
  tokensaver counts with OpenAI's `o200k_base` and multiplies by a per-model factor from
  `prices.json`. These are always shown with `~` and labelled "estimated". The factors are
  rough heuristics, not measurements; real counts can differ by 10–20% or more,
  especially for code and non-English text. For exact counts, use the provider's own
  token-counting API.
- **Input cost only.** `count`, `compare` and `optimize` price the prompt you send. Output
  tokens, cached-input discounts, batch discounts and long-context surcharges (for example
  above 200K tokens on Gemini 3.1 Pro or 100K on Claude Haiku 5.5) are not included.
- **Prices go stale.** Check the `last_updated` date in the output. Some listed prices are
  scheduled to change (see the `notes` field in `prices.json`).
- **Languages.** Token counting and the `json`, `whitespace` and `duplicates` rules work
  in every language (tested on 55, see above). The `filler` rule understands English and
  Persian; `repeated-instructions` and "Example 1:" detection, currently English only.
  Estimates for Claude and Gemini are less reliable for non-English text.
- **Message overhead is not counted.** Chat APIs add a few tokens per message for roles
  and formatting. tokensaver counts the text you give it.
- **Rules are heuristics.** Review suggestions can be wrong: a repeated sentence can be
  intentional emphasis, and "duplicate" lines can be real data. That is why they are never
  applied unless you ask.
- **Offline by design.** tokensaver makes no network calls. The tokenizer files ship
  inside the package and are checked against their published SHA-256 hashes.

## Roadmap

- [ ] Calibrate the Claude and Gemini estimate factors against official token counters
- [ ] `--json` output for CI pipelines and scripts
- [ ] Output-token and prompt-caching cost estimates
- [ ] Directory mode: scan all prompts in a project
- [ ] More rules: verbose markdown, long URLs, unused template variables
- [ ] GitHub Action that comments token savings on pull requests

Ideas and votes are welcome in the issues.

## How to contribute

⭐ **If tokensaver saved you tokens, a star helps other developers find it.**

Contributions are very welcome: new rules, better heuristics, price updates and bug
reports. Read [CONTRIBUTING.md](https://github.com/behrouzbk/tokensaver/blob/main/CONTRIBUTING.md) for the 5-minute setup. Each rule is one
small file with its own tests, so it is a good first contribution.

## Need help cutting your AI costs? Work with me

tokensaver catches the easy wins. If your AI bill is growing and you want a deeper review
of prompts, model choice, caching and architecture, I can help.

👉 **[Get in touch](https://axieo.ca)** or email **info@axieo.ca**

## Support tokensaver

☕ tokensaver is free and MIT licensed. If it saves you money, you can
[buy me a coffee](https://buymeacoffee.com/jiq8aoqxeo).

## License

[MIT](https://github.com/behrouzbk/tokensaver/blob/main/LICENSE)
