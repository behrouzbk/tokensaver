# Calibrating the Claude and Gemini token estimates

tokensaver counts tokens offline. For OpenAI models the counts are exact. Claude and
Gemini have no offline tokenizer, so tokensaver estimates their counts as
`o200k_base count x estimate_factor`, with the factor from `prices.json`. This folder
measures those factors against the providers' own counters (issue
[#3](https://github.com/behrouzbk/tokensaver/issues/3)).

> This script calls the Anthropic and Google APIs. Counting tokens generates nothing.
> Anthropic's `count_tokens` is free; Google's pages don't state a price for
> `countTokens`. It is **not** part of the tokensaver package, which never makes
> network calls.

## The corpus

[`corpus/`](corpus/) has 34 public texts, about 23,000 o200k tokens in total:

- **English prose:** the example prompts and sections of the README.
- **Code:** parts of tokensaver's own source.
- **JSON:** tool schemas (pretty and compact), a request body, `cases.json`,
  `prices.json`, a transcript.
- **12 languages, one per script:** English, French, German, Russian, Arabic, Hebrew,
  Hindi, Punjabi, Chinese, Japanese, Korean and Thai. Each is the same support-bot
  prompt (without its JSON example), so the ratios compare fairly. The translations
  were written by Claude and checked for meaning, not by native speakers; token ratios
  depend mostly on the script, not on perfect wording.
- **Mixed:** the 55 one-line language samples from `tests/test_languages.py`.

## Method

1. Count each text offline with `o200k_base`, exactly as tokensaver does.
2. Count it with the official counter for each model: Anthropic `messages.count_tokens`
   and Gemini `countTokens`.
3. The API adds a few framing tokens per request. Measure them by counting three texts
   once and twice in a row (`2 x count(text) - count(text twice)`), and subtract them.
4. The fitted factor is the **median** of `official / o200k` over all texts, so one
   unusual script cannot pull it far. The summary also shows the ratio for each kind
   of text, and the median error of the current and fitted factors.

## How tokensaver uses the factors

The text is tokenized once with `o200k_base`. Each token is weighted by the factor of the
script of the first letter it covers (spaces, digits and punctuation go with the script
around them; Han counts as Japanese when the text has kana). Tokens of other scripts,
including Latin, use the model's `estimate_factor`. Text with no measured script is
estimated exactly as before.

## Results: Claude (2026-11-07)

Full tables in [`results/summary.md`](results/summary.md), raw counts in
[`results/counts.json`](results/counts.json).

- **Claude Fable 5.1, Opus 5.5, Sonnet 5.5 and Haiku 5.5 count every text identically**,
  so they share one set of factors. Haiku 4.5 uses the older tokenizer.
- **English, code and JSON: the old factors were already right.** Claude 5.x uses 1.33 to
  1.69 times the o200k count (factor 1.5), Haiku 4.5 1.09 to 1.26 (factor 1.15). They are
  unchanged.
- **Other scripts were badly undercounted.** Claude tokens per o200k token, for the same
  text: Gurmukhi (Punjabi) 3.90, Thai 2.39, Devanagari (Hindi) 2.31, Arabic 2.17, Hebrew
  1.86, Hangul (Korean) 1.86, Cyrillic (Russian) 1.74, Chinese 1.52, Japanese 1.33. These
  are now `script_factors` in `prices.json`, applied to the tokens of a text written in
  that script.
- **Not fixed: other Latin-script languages.** A script cannot tell German from English,
  so German (2.15 on Claude 5.x) and French (1.78) still use the English factor and are
  undercounted by about 30% and 16%.

## Results: Gemini (2026-11-07)

- **Gemini 3.8 Flash and 3.1 Pro count every text identically.** Gemini 4 Argon is close,
  and adds 31 framing tokens per request (the others add none).
- **The language gap is small on Gemini.** Gemini tokens per o200k token: Hebrew 1.24,
  Arabic 1.18, Gurmukhi (Punjabi) 1.09, Cyrillic 1.06, Hangul 1.02, Chinese 1.00,
  Devanagari 0.87, Thai 0.83, Japanese 0.79 (3.8 Flash; Argon is slightly lower). The old
  single factor of 1.05 was up to 42% too high on Thai and Japanese.
- **Default factor 1.05 → 1.10.** English prose is 1.07–1.08, code 1.17–1.19 and JSON
  1.21–1.22. One factor covers all Latin-script text, so 1.10 is a compromise: English
  prose +2%, code -7%, JSON -10% (before: -3%, -12%, -14%).
- **Not measured:** `gemini-2.5-flash` and `gemini-2.5-flash-lite` return "no longer
  available to new users". They use Gemini 3.8 Flash's factors.

## Check on text no factor was fitted on

The 55 one-line language samples, counted as one text. Error of the estimate:

- Claude Sonnet 5.5: 26% too low before, 20% too low now.
- Claude Haiku 4.5: 26% too low before, 13% too low now.
- Gemini 3.8 Flash: 5% too high before, 7% too high now. Gemini 4 Argon: 5% → 6%.

What is left comes from scripts without a factor yet (Bengali, Greek, Kannada, Khmer,
Malayalam, Myanmar, Tamil, Telugu) and, on Claude, from Latin-script languages.

A correction to the first Claude results: the version in 0.7.0 counted each script's part
of a text separately, which added tokens at every cut (+6% on this text) and made the
Claude numbers above look better (15% and 6% too low). tokensaver now tokenizes the whole
text once and only weights each token by its script, so the total always matches the
o200k count.

## Run it

```bash
pip install prompt-tokensaver anthropic
python calibrate.py --dry-run         # offline counts only, no API calls
python calibrate.py --only claude     # ANTHROPIC_API_KEY or an `ant auth login` profile
python calibrate.py --only gemini     # GEMINI_API_KEY or GOOGLE_API_KEY
python calibrate.py --analyze         # rebuild the summary from saved counts
python chart.py                       # redraw the README chart (assets/language-tax-*.svg)
```

Counts are saved in `results/counts.json` after each provider, and the analysis in
`results/summary.md`.
