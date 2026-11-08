## Limitations

Please read this before relying on the numbers.

- **Exact vs estimated.** Counts are exact only for OpenAI models that `tiktoken` maps to a
  tokenizer (shown as "exact"). Claude, Gemini and GPT-6 have no offline tokenizer, so
  tokensaver counts with OpenAI's `o200k_base` and multiplies by a per-model factor from
  `prices.json`. These are always shown with `~` and labelled "estimated". The factors are
  rough heuristics, not measurements; real counts can differ by 10–20% or more,
  especially for code and non-English text. For exact counts, use the provider's own
  token-counting API.
- **Input cost only.** `count`, `compare`, `optimize`, `scan` and `request` price the
  prompt you send. Output tokens, batch discounts and long-context surcharges (for example
  above 200K tokens on Gemini 3.1 Pro or 100K on Claude Haiku 5.5) are not included.
  Prompt-caching prices are used only by `request` and `optimize --cache-hit-rate`,
  and only for the fixed part.
- **Caching estimates are estimates.** They assume the whole fixed part is cached and use
  the default (shortest) cache: 5 minutes on Claude, 30 minutes on GPT-6. Longer caches cost
  more to write, Gemini's explicit caching adds a storage fee, and whether a call actually
  hits the cache depends on traffic, routing and expiry. Use `tokensaver cache-check` to
  make sure the fixed part is identical between calls.
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
