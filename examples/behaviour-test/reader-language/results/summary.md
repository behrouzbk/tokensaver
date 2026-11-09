# Behaviour test results

Model: `claude-sonnet-5-5` (effort low). Judge: `claude-haiku-5-5`. 5 runs per case and prompt.
A = "reply in the user's language", B = "write in the language of whoever will read the text".

| Case | A passes | B passes | Note |
|---|---:|---:|---|
| Owner asks in Italian, the email to a German client is in German | 5/5 | 5/5 |  |
| Forwarding a German thread to a teammate uses the teammate's language, not the thread's | 0/5 | 4/5 | B better |
| A teammate who speaks two languages gets the first one listed | 0/5 | 5/5 | B better |
| A summary for the owner stays in the owner's language, not the thread's | 5/5 | 5/5 |  |

B did better than A on: 2-forward-to-teammate, 3-first-listed-language, and no case dropped.

Tokens: bot 134,049 in / 17,037 out; judge 40,227 in / 7,065 out. Estimated cost: $0.45.
