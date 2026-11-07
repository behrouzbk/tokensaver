# Try tokensaver: an English test, step by step

This guide tests tokensaver end to end with English prompts. Every step lists the result
you should see, so you can tell at a glance that it works.

You will:

1. Measure how much of each request is the **fixed part** (system prompt + tool schemas)
   and how much is the user's message (`tokensaver request`).
2. Find the waste in a long system prompt and save an optimized copy (`tokensaver optimize`).
3. Measure again to see the saving on **every** request.
4. Check that two requests share the same start, so prompt caching can reuse it
   (`tokensaver cache-check`).

The expected numbers are for tokensaver **0.4.0** on `gpt-4o` (exact counts), with prices
as of 2026-11-07. Token counts stay the same on later versions; dollar amounts change
when prices are updated.

## Files used

| File | What it is |
|---|---|
| [`messy_prompt.txt`](messy_prompt.txt) | A customer-support system prompt (834 tokens). |
| [`support_bot_prompt.txt`](support_bot_prompt.txt) | A longer support-bot system prompt with typical waste: polite filler, pretty-printed JSON, a duplicate line, a paragraph pasted twice and a repeated rule (431 tokens). |
| [`tools.json`](tools.json) | Two tool definitions in OpenAI format: `get_order_status` and `create_refund`. |
| [`request_1.json`](request_1.json), [`request_2.json`](request_2.json) | Two Chat Completions request bodies with the tools and the support-bot prompt, plus the current date and time at the top of the system prompt (Test 3). |

## Setup

Use a fresh folder and virtual environment, so you test the published package.

**Windows (PowerShell)**

```powershell
mkdir C:\tokensaver-test
cd C:\tokensaver-test
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --upgrade prompt-tokensaver
tokensaver version

$base = "https://raw.githubusercontent.com/behrouzbk/tokensaver/main/examples"
foreach ($f in "messy_prompt.txt", "support_bot_prompt.txt", "tools.json", "request_1.json", "request_2.json") {
    Invoke-WebRequest "$base/$f" -OutFile $f
}
```

If PowerShell says running scripts is disabled, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

**macOS / Linux**

```bash
mkdir ~/tokensaver-test && cd ~/tokensaver-test
python3 -m venv venv
source venv/bin/activate
pip install --upgrade prompt-tokensaver
tokensaver version

base=https://raw.githubusercontent.com/behrouzbk/tokensaver/main/examples
for f in messy_prompt.txt support_bot_prompt.txt tools.json request_1.json request_2.json; do curl -sLO "$base/$f"; done
```

✅ `tokensaver version` prints `0.4.0` or newer, and the folder has the five files.

> **Tip:** download the files rather than pasting them into the terminal. Pasting long
> multi-line text into the PowerShell console can silently drop characters. If you
> want to write your own prompt, use an editor (`notepad my_prompt.txt`).

The commands below are the same on every system.

## Test 1: how much of a request is the fixed part?

### 1a. One English question

```powershell
tokensaver request --system messy_prompt.txt --tools tools.json --user "Where is my order?"
```

✅ Expected:

| Part | Tokens | $/1k calls |
|---|---:|---:|
| System prompt (`messy_prompt.txt`) | 834 | $2.08 |
| Tool schemas (2 tools) | ~142 | $0.3550 |
| **Fixed part** | **~976** | **$2.44** |

| User message | User tokens | Request tokens | Fixed share | $/1k calls |
|---|---:|---:|---:|---:|
| Where is my order? | 5 | ~981 | 99% | $2.45 |

And the line: *"The fixed part is 99% of each request."*

`~` means estimated: tool schemas are always estimated, because providers turn them into
their own hidden format before the model sees them.

### 1b. A short and a long question side by side

```powershell
tokensaver request --system messy_prompt.txt --tools tools.json --user "Where is my order?" --user "Please give me a detailed explanation of every step of the refund process, including timelines."
```

✅ Expected:

| User message | User tokens | Request tokens | Fixed share |
|---|---:|---:|---:|
| Where is my order? | 5 | ~981 | 99% |
| Please give me a detailed explanation o… | 17 | ~993 | 98% |

And: *"The fixed part is 98% to 99% of each request."* The long message is cut with `…`
to keep the table narrow.

**What this shows:** even a long question is only 1–2% of the request. The rest is the
system prompt and tools, which you pay for on every call.

## Test 2: optimize a long system prompt and measure the saving

### 2a. Measure before optimizing

```powershell
tokensaver request --system support_bot_prompt.txt --tools tools.json --user "Where is my order?" --user "Please give me a detailed explanation of every step of the refund process, including timelines."
```

✅ Expected: System prompt `431`, Tool schemas `~142`, **Fixed part `~573`** ($1.43 per
1k calls). Request tokens `~578` and `~590`, and *"The fixed part is 97% to 99% of each
request."*

### 2b. See the suggestions (nothing is saved yet)

```powershell
tokensaver optimize support_bot_prompt.txt
```

✅ Expected: 8 suggestions, then a before/after diff.

| # | Suggestion | Tokens | Status |
|---|---|---:|---|
| 1 | Minify JSON block | -23 | applied (safe) |
| 2 | Duplicate line: "Standard shipping takes 3 to 5 business days." | -11 | review |
| 3 | Near-duplicate (97% similar) paragraph: the returns policy | -53 | review |
| 4 | Repeated instruction: "Remember to always respond in English." | -8 | review |
| 5 | Filler: "I would like you to…" | -6 | review |
| 6 | Filler: "As an AI…" | -6 | review |
| 7 | Filler: "in order to → to" | -2 | review |
| 8 | Filler: "Thank you in advance" (×2) | -12 | review |

Only safe fixes are applied by default: **Before 431, After 408, Saved 23 tokens (5.3%)**.
The line *"7 review suggestion(s) not applied; applying all of them saves 98 more
tokens"* tells you what the review fixes would add.

### 2c. Apply all fixes and save the optimized prompt

```powershell
tokensaver optimize support_bot_prompt.txt --apply all -o support_bot_prompt.min.txt
```

✅ Expected: **Before 431, After 310, Saved 121 tokens (28.1%)** = $0.3025 per 1,000
calls, $302.50 per 1M calls. Then *"Saved optimized prompt to support_bot_prompt.min.txt"*.
The original `support_bot_prompt.txt` is never changed.

Look at the result:

```powershell
Get-Content support_bot_prompt.min.txt      # macOS / Linux: cat support_bot_prompt.min.txt
```

✅ Expected:

- Filler rewritten as direct instructions: "Help customers with questions about…", "You
  should always be polite, patient and clear.", "To protect customer data, …".
- The JSON format on one line, with the same keys and values.
- Removed: the duplicate shipping line, the second copy of the returns paragraph, the
  repeated "respond in English" rule and the two thank-you lines.
- Every rule and fact still there.

### 2d. Measure again with the optimized prompt

```powershell
tokensaver request --system support_bot_prompt.min.txt --tools tools.json --user "Where is my order?" --user "Please give me a detailed explanation of every step of the refund process, including timelines."
```

✅ Expected: System prompt `310`, **Fixed part `~452`** ($1.13 per 1k calls, was $1.43).
Request tokens drop from `~578` / `~590` to `~457` / `~469`.

| | Before | After |
|---|---:|---:|
| System prompt | 431 | 310 |
| Fixed part | ~573 | ~452 |
| Request with "Where is my order?" | ~578 | ~457 |
| Cost per 1k calls | $1.45 | $1.14 |

**What this shows:** optimizing the system prompt saved 121 tokens on every request,
more than 7 times the longest user message (17 tokens).

## Test 3: do the requests share a cacheable prefix?

Prompt caching reuses the start of a request only when it is byte-identical to an earlier
one. Both request files put the current date and time at the top of the system prompt,
a common pattern that changes on every call.

```powershell
tokensaver cache-check request_1.json request_2.json
```

✅ Expected:

| Request | Tokens | Shared prefix | After it |
|---|---:|---:|---:|
| request_1.json | ~599 | ~160 | ~439 |
| request_2.json | ~604 | ~160 | ~444 |

- Both requests leave the shared prefix in `messages[0] (system)` at line 1, column 39,
  on `2026-11-07 10:15` and `2026-11-07 10:16`, marked `date/time`.
- A red line: the fixed part differs, so the cache can reuse at most the first ~160
  tokens (the tool schemas and the words before the date).
- A tip to move the date and time after the static part, for example into the user
  message, and a warning that 160 tokens is below the 1,024-token minimum.

**What this shows:** one changing line at the top of the system prompt means about 440
tokens per request can never come from the cache.

```powershell
# The same check as JSON, for CI: prints true while the fixed part differs
tokensaver cache-check request_1.json request_2.json --json
```

✅ `"fixed_part_differs": true` and `"shared_prefix": {"tokens": 160, ...}`.

## More checks (optional)

```powershell
# JSON output for scripts and CI
tokensaver request --system support_bot_prompt.txt --tools tools.json --user "Where is my order?" --json
```

✅ `"fixed": {"tokens": 573, ...}` and one request with `"tokens": 578` and
`"fixed_percent": 99.13`.

```powershell
# Another model (Claude counts are estimates, shown with ~)
tokensaver request --system support_bot_prompt.txt --tools tools.json -m claude-sonnet-5-5
```

✅ `(estimated)` in the header, System prompt `~646`, Tool schemas `~213`, Fixed part
`~859`, and a yellow note explaining the estimate.

```powershell
# What prompt caching does to the fixed part (needs 0.5.0 or newer)
tokensaver request --system support_bot_prompt.txt --tools tools.json -m claude-sonnet-5-5 --cache-hit-rate 0.9
```

✅ A **Fixed part with prompt caching** table, per 1,000 calls: No caching `$1.72`, First
call `$2.15` (writing the cache costs 1.25×), Later calls `$0.0859`, and Average at 90%
cache hits `$0.2921`. Below it: "A cached call pays 95% less for the fixed part."

```powershell
# A fixed part too short to be cached (needs 0.5.0 or newer)
tokensaver request --system support_bot_prompt.txt --tools tools.json -m gpt-6.1-sol
```

✅ A yellow note instead of the caching table: the fixed part (`~573` tokens) is below
gpt-6.1-sol's minimum of 1,024 tokens, so every call pays the full input price.

```powershell
# Errors: each prints a red "Error:" and stops
tokensaver request --user "Hi"                    # needs --system or --tools
tokensaver request --system nope.txt              # File not found: nope.txt
```

## Clean up

```powershell
deactivate
cd C:\                                   # macOS / Linux: cd ~
Remove-Item -Recurse -Force C:\tokensaver-test    # macOS / Linux: rm -rf ~/tokensaver-test
```

## Something different?

If a result doesn't match, [open an issue](https://github.com/behrouzbk/tokensaver/issues)
with the command, your output and `tokensaver version`.
