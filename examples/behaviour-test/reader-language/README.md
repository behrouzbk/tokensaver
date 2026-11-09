# Behaviour test: is text for someone else in their language?

"Reply in the user's language" sounds complete until the text is not for the user. An
owner asks in Italian for an email to a German client, and the email comes out in
Italian: fluent, and still wrong. The rule that holds is about the reader: **write in the
language of whoever will read the text.** No token count catches this, so this suite
checks it on real model calls.

- **A**: [`prompt_user_language.txt`](prompt_user_language.txt) says "Reply in the user's
  language."
- **B**: [`prompt_reader_language.txt`](prompt_reader_language.txt) says to write in the
  reader's language. For a client, that is the language of the thread being answered.
  For a teammate, it is the first language in their `spoken_languages` field.

The setup follows how a reader described their own agent: clients get the thread's
language, and teammates get the language stored in the team directory.

Both prompts get the same tools ([`tools.json`](tools.json)): `get_thread`,
`find_team_member` and `draft_email`. Drafts are only saved, never sent, and every tool
returns fixed data from [`cases.json`](cases.json) (`fixtures`).

## The cases

1. **Recipient language:** the owner asks in Italian for a reply to a German client
   thread. The draft must be in German and go to the client. The message to the owner
   must be in Italian.
2. **Forward to a teammate:** the owner asks in English to forward the gist of the German
   thread to Giulia (`spoken_languages: Italian, English`). The draft must be in Italian,
   not the thread's German and not the owner's English. The message to the owner must be
   in English.
3. **First listed language:** the owner asks in German for a note to Tom
   (`spoken_languages: English, German`). The draft must be in English, even though Tom
   also speaks German.
4. **Summary for the owner (control):** the owner asks in Italian for a summary of the
   German thread. The reader is the owner, so the summary must be in Italian, and no
   draft is made.

Case 4 is there so that B gets no credit for always writing in the thread's language.

Code checks the tool calls (was a draft saved, and to whom). The judge model reads the
draft body and the reply and answers the language questions.

## Results

Run on 2026-11-08: `claude-sonnet-5-5` (effort low), judged by `claude-haiku-5-5`, 5 runs
per case and prompt, about $0.45. Full table: [`results/summary.md`](results/summary.md).
Every conversation: [`results/transcripts/`](results/transcripts/).

| Case | A: user's language | B: reader's language |
|---|---:|---:|
| 1. Reply to a German client, asked in Italian | 5/5 | 5/5 |
| 2. Forward a German thread to an Italian teammate, asked in English | 0/5 | 4/5\* |
| 3. Teammate whose first language is English, asked in German | 0/5 | 5/5 |
| 4. Summary for the owner (control) | 5/5 | 5/5 |

What the transcripts show:

- **A's failures follow the user, not the reader.** In case 2, all five of A's drafts to
  Giulia were in English, the owner's language. In case 3, all five drafts to Tom were in
  German ("Hallo Tom, die Besprechung morgen ist auf 15 Uhr verschoben."). Both read
  fine, and both are wrong.
- **Case 1 passes with either prompt.** When the reader is a client and the thread is in
  their language, the model answers in the thread's language even without being told.
  So the plain rule breaks for teammates and forwarded threads, not for direct replies.
- **B never broke the control.** Summaries for the owner stayed in Italian, so B does
  not simply copy the thread's language.

\* B's one miss in case 2 is a judge error. The draft
([`2-forward-to-teammate_B_4.json`](results/transcripts/2-forward-to-teammate_B_4.json))
is all Italian, and the judge's own reason ends with "the body is in Italian and the
answer should be true", yet it answered false. The table above is left as graded.

## Run it

From the folder above:

```bash
python run.py --suite reader-language --dry-run   # no API calls
python run.py --suite reader-language             # 4 cases x 2 prompts x 5 runs
```

Results go to `reader-language/results/`.
