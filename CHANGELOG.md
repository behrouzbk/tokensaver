# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Gemini token estimates are now calibrated against Google's `countTokens` (#3), with the
  same per-script factors as Claude. Gemini's language gap is small: 0.79 (Japanese) to
  1.24 (Hebrew) tokens per o200k token, so the old estimates were up to 42% too high on
  Thai and Japanese. The default factor goes from 1.05 to 1.10, which brings code and
  JSON closer (now about 7-10% low instead of 12-14%) and English prose to +2%.
- `gemini-2.5-flash` and `gemini-2.5-flash-lite` are closed to new API users, so they
  could not be measured. They stay listed, with a note, and use Gemini 3.8 Flash's
  factors.

### Fixed
- Estimates for text that mixes scripts counted each script's part separately, which
  added a token at almost every switch (+6% on the 55-language sample). The whole text
  is now tokenized once and each token is weighted by its script, so the total always
  matches the o200k count. This makes the 0.7.0 Claude numbers for mixed text a little
  less flattering: on the 55-language sample, Claude Sonnet 5.5 is 20% too low (0.7.0
  reported 15%).

## [0.7.0] - 2026-11-07

### Changed
- Claude token estimates are now calibrated against Anthropic's token counter (#3). The
  factors for English, code and JSON were already right and are unchanged. Text in
  Arabic, Hebrew, Devanagari, Gurmukhi, Thai, Hangul, Cyrillic, Chinese or Japanese now
  gets its own measured factor: before, Claude estimates for those scripts were up to 71%
  too low (Punjabi), and 14-52% too low for most of the others. `prices.json` has a new
  optional `script_factors` per model.

### Added
- `examples/calibration/`: the corpus, script and results behind the new factors.

### Added
- `examples/behaviour-test/`: checks on a real model that the optimized support-bot
  prompt (431 → 310 tokens) behaves like the original, across 9 support cases. Both
  passed 45 of 45 on `claude-sonnet-5-5`; results and transcripts are included. Not part
  of the package, which still makes no network calls.

## [0.6.0] - 2026-11-07

### Added
- `optimize --cache-hit-rate`: also shows what the saving is worth with prompt caching,
  per 1,000 calls with no caching, on the first call, on a cached call and on average.
  `--tools` adds tool schemas so the saving covers the whole fixed part. Warns when the
  prompt is too short to be cached, and when optimizing would push it below the minimum.
  `--json` gets a `caching` object when the option is used. Default output is unchanged
  (#20).

## [0.5.0] - 2026-11-07

### Added
- `request` shows what the fixed part costs with prompt caching: with no caching, on the
  first call (cache write), on later calls (cache read) and, with `--cache-hit-rate`, on
  average. When the fixed part is below the model's minimum cacheable length, it says the
  prefix is never cached. `--json` has a new `caching` object (#15).
- `prices.json`: `cached_input_per_1m` for every model, plus `cache_write_per_1m` and
  `min_cacheable_tokens` where the provider publishes them. `tokensaver models` shows the
  cached input price.

### Changed
- Prices checked against the OpenAI, Anthropic and Google pricing pages on 2026-11-07.
  Input and output prices are unchanged.

## [0.4.0] - 2026-11-07

### Added
- `tokensaver cache-check REQUEST...`: compares two or more requests (request bodies as
  JSON, or plain-text system prompts with optional `--tools`) and shows the prefix they
  share, where each one leaves it (part, line, column and text), whether the fixed part
  (tools or system prompt) differs, and whether the differing value looks like a date,
  time or ID that breaks prompt caching on every call. Warns when the shared prefix is
  below `--min-tokens` (default 1,024). Supports `--json` (#14).

## [0.3.1] - 2026-11-06

### Fixed
- `request`: the fixed part's share no longer rounds to 100% (or 0%) when it is not.
  A 4-token message against a 976-token system prompt now shows 99.6%, not 100%, which
  read as if the user message cost nothing.

## [0.3.0] - 2026-11-06

### Added
- `tokensaver request`: splits a request into its fixed part (`--system` prompt and
  `--tools` schemas, sent with every call) and the `--user` message, with tokens, cost and
  the fixed part's share of each request. Repeat `--user` to compare messages, for example
  the same question in different languages. Tool schemas are counted as compact JSON and
  labelled as estimates. Supports `--json` (#10).

## [0.2.0] - 2026-10-29

### Added
- `tokensaver scan FOLDER`: measures every prompt file in a folder and its subfolders,
  with what the safe fixes and all fixes would save per file, biggest saving first, and
  a total. `--glob` picks the file patterns. Hidden folders, `node_modules`,
  `__pycache__` and Python virtual environments are skipped (#4).
- `--json` for `count`, `compare`, `optimize` and `scan`: prints one JSON object instead
  of tables, for scripts and CI (#2).

## [0.1.5] - 2026-10-29

### Added
- `filler` now removes Persian filler: «لطفاً», «از تو/شما می‌خواهم که…» and
  «ممنون می‌شوم اگر…», including the common ZWNJ-as-space and no-ZWNJ spellings
  (thanks @AliAsgharPZ, #6).

## [0.1.4] - 2026-10-26

Documentation only; no change to how tokensaver works.

### Fixed
- README: the "Works in every language" section now says that `repeated-instructions`
  and "Example 1:" detection are English-only, like `filler`. It previously named only
  `filler`, which disagreed with the Limitations section.

## [0.1.3] - 2026-10-26

### Fixed
- Suggestion previews are cut by screen width, so Chinese, Japanese and Korean text no
  longer pushes titles onto a second line in the suggestions table.

### Added
- README: "Commands and options" guide (`--apply`, `--output`/`-o`, `--force`,
  `--no-diff`, `--model`, `--models`, `--prices`, and input forms).
- README: "Support tokensaver" section and a Sponsor button (`.github/FUNDING.yml`).

### Changed
- README "Work with me" links to https://axieo.ca.

## [0.1.2] - 2026-10-26

### Fixed
- `duplicates` now finds repeated lines in Chinese, Japanese and Korean. Short lines are
  skipped by token count instead of character count, which wrongly skipped dense scripts.

### Added
- 🌍 Multilingual support is now tested in CI: counting, `json`, `whitespace` and
  `duplicates` on 55 languages, including right-to-left scripts and languages without
  spaces.
- README: "Works in every language" section with the full list.

## [0.1.1] - 2026-10-26

Fixes the PyPI project page (images and links); no change to how tokensaver works.

### Added
- Demo image and PyPI badge in the README; README links are absolute so they work on PyPI.
- Issue forms, pull request template, code of conduct and security policy.
- PyPI publishing workflow (trusted publishing, no stored token).

### Changed
- CI uses `actions/checkout@v7` and `actions/setup-python@v7`.

## [0.1.0] - 2026-10-26

First release, published on PyPI as `prompt-tokensaver` (command: `tokensaver`).

### Added
- Project setup: `pyproject.toml`, `src/` layout, ruff, pytest.
- Offline token counting with bundled tiktoken encodings (`o200k_base`, `cl100k_base`).
- `prices.json` with 20 OpenAI, Anthropic and Google models, source URLs and `last_updated`.
- Optimizer with six rules: `json` and `whitespace` (safe), `duplicates`,
  `repeated-instructions`, `filler` and `long-examples` (review; long-examples only flags).
- CLI: `count`, `compare`, `optimize` (`--apply`, `--output`, `--force`, `--no-diff`),
  `models`, `version`; input from a file, stdin (`-`) or literal text; `--prices` override.
- Line numbers in suggestions always refer to the original file.
- Few-shot examples are protected from wording rules.
- `examples/messy_prompt.txt`, README, CONTRIBUTING and CI (ruff + pytest on Windows,
  macOS and Linux, Python 3.10 and 3.13).
