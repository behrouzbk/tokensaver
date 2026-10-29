# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
