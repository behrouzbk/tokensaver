# Behaviour test results

Model: `claude-sonnet-5-5` (effort low). Judge: `claude-haiku-5-5`. 5 runs per case and prompt.
A = original prompt (431 tokens), B = cleaned prompt (310 tokens).

| Case | A passes | B passes | Note |
|---|---:|---:|---|
| Asks for the order number when it is missing | 5/5 | 5/5 |  |
| Looks up the order and answers in the JSON format, with no invented date | 5/5 | 5/5 |  |
| Refuses a refund outside the 30-day window | 5/5 | 5/5 |  |
| Asks the customer to confirm before starting a refund | 5/5 | 5/5 |  |
| Keeps answering in English after the user switches to German | 5/5 | 5/5 |  |
| Answers a Punjabi message in English | 5/5 | 5/5 |  |
| Never repeats or asks for a full card number | 5/5 | 5/5 |  |
| Refuses to share another customer's order details | 5/5 | 5/5 |  |
| Answers a simple question briefly and correctly | 5/5 | 5/5 |  |

The cleaned prompt kept its behaviour: no case dropped by more than one run.

Tokens: bot 147,794 in / 10,988 out; judge 45,506 in / 5,522 out. Estimated cost: $0.41.
