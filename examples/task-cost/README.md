# Cost per successful task: an example

Cost per request can go down while cost per task goes up. A shorter prompt that leaves
out an instruction the model needed can lead to a retry or a follow-up turn, and then
the saving costs more than it saved. `tokensaver task-cost` reads a log of real API
calls and shows both numbers side by side.

> **These two logs are made up.** They show the format and the effect, not a
> measurement. The usage blocks have the same shape as real Anthropic responses, but the
> numbers were written by hand. Run the command on your own logs for real figures.

## The files

| File | What it is |
|---|---|
| [`before.jsonl`](before.jsonl) | 8 support tasks with a 1,431-token cached system prompt. 9 calls; 7 tasks passed. |
| [`after.jsonl`](after.jsonl) | The same 8 tasks after trimming the prompt to 1,110 tokens. The refund rule got lost in the trim, so refunds need more turns: 14 calls; 6 tasks passed. |

One line per call:

```json
{"task": "t1", "type": "refund", "passed": true, "response": {"model": "claude-sonnet-5-5-20261001", "usage": {"input_tokens": 35, "cache_read_input_tokens": 1110, "cache_creation_input_tokens": 0, "output_tokens": 160}}}
```

## Run it

```bash
tokensaver task-cost before.jsonl after.jsonl
```

✅ Expected (per log):

| | before.jsonl | after.jsonl | Change |
|---|---:|---:|---:|
| Passed / failed / unknown | 7 / 1 / 0 | 6 / 2 / 0 | |
| Calls per task | 1.12 | 1.75 | +56% |
| Input read from cache | 86% | 89% | |
| Cost per call | $0.001977 | $0.001764 | **-11%** |
| Cost per task | $0.002224 | $0.003086 | +39% |
| **Cost per successful task** | **$0.002542** | **$0.004115** | **+62%** |

Then a table by task type (order-status got cheaper, refund got 3× more expensive) and
a red line: *"Cheaper per call … but more expensive per successful task … the saving is
lost to failures and extra calls."*

**What this shows:** the trim did its job per call, 11% cheaper. But each successful task
cost 62% more, because refunds now take extra turns and fail more often. A token counter
alone would have called this a win.

## Logging your own calls

Write one JSON line per API call, with:

- `task`: an ID shared by every call that belongs to one task (retries and follow-ups
  included).
- `response`: the raw API response, or just its `usage` block (then add `model`).
- `passed`: `true` or `false`, on any of the task's lines (the last one given wins).
  Use whatever check you trust: a test, a judge, a human label. Tasks without it are
  reported as unknown and left out of cost per successful task.
- `type` (optional): groups tasks in a second table.

Anthropic, OpenAI (Chat Completions and Responses) and Gemini responses are understood.
Costs use the usage counts the provider returned, times the standard-tier prices in
`prices.json`, so they track your bill closely but are not your invoice.
