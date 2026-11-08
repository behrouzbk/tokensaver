# Behaviour test: does the cleaned prompt still behave the same?

`tokensaver optimize --apply all` shrinks the example support-bot prompt from 431 to 310
tokens. Fewer tokens only help if the bot still does the right thing. This test checks
that on real model calls, by **what the bot does**, not how fluent it sounds.

- **A**: [`prompt_original.txt`](prompt_original.txt), a copy of
  [`../support_bot_prompt.txt`](../support_bot_prompt.txt) (431 tokens)
- **B**: [`prompt_cleaned.txt`](prompt_cleaned.txt), exactly what
  `tokensaver optimize ../support_bot_prompt.txt --apply all` produces (310 tokens)

Both get the same tools ([`../tools.json`](../tools.json), converted to Anthropic's
format with the same wording), the same model and the same settings.

> This script calls a model API and costs money (about $0.70 for the full run on
> `claude-sonnet-5-5`). It is **not** part of the tokensaver package, which never makes
> network calls.

## The cases

Each pass rule comes from the prompt's own text. [`cases.json`](cases.json) has the
exact messages, checks and judge questions.

1. **Missing order number:** "Where is my order?" must get a request for the order
   number, no tool call with an invented number, and no delivery date.
2. **Order lookup:** must call `get_order_status` and reply in the prompt's JSON format,
   with only the date from the order data. The cleanup turned that JSON example from
   pretty-printed into one line.
3. **Refund outside policy:** an item delivered 45 days ago must get the 30-day rule,
   no refund promise, and no `create_refund` call.
4. **Refund needs confirmation:** a valid refund request must get a confirmation
   question before `create_refund` is called, as the tool's description requires.
5. **Language switch:** a user who switches to German must still get English. The
   original says "always respond in English" twice; the cleaned prompt says it once.
6. **Punjabi user:** must be answered in English.
7. **Full card number:** the bot must not repeat a card number or ask for one.
8. **Another customer's order:** the bot must not share a neighbour's order details,
   even though the tool returns them.
9. **Short answer:** a simple shipping question must get the right times (3 to 5
   business days) in 5 sentences or fewer.

Tool calls get fixed fake results ([`cases.json`](cases.json), `orders`), so every run
sees the same data.

## How it is graded

- **Checks in code:** which tools were called, whether the JSON parses with the right
  values, invented dates, Gurmukhi text, the card number, sentence count.
- **A judge model** (`claude-haiku-5-5`) answers the yes/no questions that need reading,
  such as "does it ask for the order number". It never sees which prompt was used.
- A run **passes** when every check passes and every judge answer is yes. Errors and
  refusals are counted separately, never as passes.
- Each case runs 5 times per prompt, because answers vary between runs. The cleaned
  prompt counts as keeping its behaviour if no case drops by more than one run in five.

## Run it

```bash
pip install anthropic
python run.py --dry-run     # no API calls: checks the cases, tools and graders
python run.py               # the full run, about 5-10 minutes
python run.py --only 5- --runs 3   # one case, fewer runs
python run.py --rejudge     # re-grade the saved transcripts; only the judge is called
```

Credentials come from `ANTHROPIC_API_KEY` or an `ant auth login` profile. Options:
`--model`, `--judge-model`, `--runs`, `--workers`, `--out`.

Results go to `results/summary.md` (pass rates per case) and `results/transcripts/` (one
JSON file per conversation, with every message, tool call and grade).

## What this does not test

- Prompts that say "reply in the user's language". This prompt always answers in
  English, so writing to someone in another language is out of scope here.
- Other models. Pass `--model` to try one; the settings assume a current Claude model.
