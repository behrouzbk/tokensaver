# Token estimate calibration

34 texts in `corpus/`. Each text is counted offline with o200k (as tokensaver
does) and with the provider's official counter. The API adds a few framing tokens
per request; that overhead is measured by counting a few texts once and twice in a
row, and subtracted. The fitted factor is the median of `(official - overhead) / o200k`
over all texts, so one unusual script cannot pull it far.

| Model | Current factor | Fitted factor | Overhead | Median error now | Median error fitted |
|---|---:|---:|---:|---:|---:|
| claude-fable-5-1 | 1.50 | 1.539 | +7.0 | 4.7% | 6.5% |
| claude-opus-5-5 | 1.50 | 1.539 | +7.0 | 4.7% | 6.5% |
| claude-sonnet-5-5 | 1.50 | 1.539 | +7.0 | 4.7% | 6.5% |
| claude-haiku-5-5 | 1.50 | 1.539 | +7.0 | 4.7% | 6.5% |
| claude-haiku-4-5 | 1.15 | 1.230 | +6.0 | 6.5% | 7.9% |
| gemini-4-argon | 1.05 | 1.095 | +31.0 | 7.7% | 6.8% |
| gemini-3.8-flash | 1.05 | 1.102 | +0.0 | 7.1% | 6.9% |
| gemini-3.1-pro-preview | 1.05 | 1.102 | +0.0 | 7.1% | 6.9% |

## Ratio by kind of text (median, min-max)

| Kind | claude-fable-5-1 | claude-opus-5-5 | claude-sonnet-5-5 | claude-haiku-5-5 | claude-haiku-4-5 | gemini-4-argon | gemini-3.8-flash | gemini-3.1-pro-preview |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Arabic | 2.17 | 2.17 | 2.17 | 2.17 | 2.17 | 1.12 | 1.18 | 1.18 |
| Chinese | 1.52 | 1.52 | 1.52 | 1.52 | 1.53 | 0.97 | 1.00 | 1.00 |
| English | 1.49 | 1.49 | 1.49 | 1.49 | 1.14 | 1.08 | 1.09 | 1.09 |
| English prose | 1.51 (1.41-1.56) | 1.51 (1.41-1.56) | 1.51 (1.41-1.56) | 1.51 (1.41-1.56) | 1.11 (1.09-1.15) | 1.07 (0.99-1.10) | 1.08 (1.02-1.10) | 1.08 (1.02-1.10) |
| French | 1.78 | 1.78 | 1.78 | 1.78 | 1.46 | 1.09 | 1.09 | 1.09 |
| German | 2.15 | 2.15 | 2.15 | 2.15 | 1.60 | 1.06 | 1.07 | 1.07 |
| Hebrew | 1.86 | 1.86 | 1.86 | 1.86 | 1.86 | 1.19 | 1.24 | 1.24 |
| Hindi | 2.31 | 2.31 | 2.31 | 2.31 | 2.31 | 0.98 | 0.87 | 0.87 |
| JSON | 1.43 (1.33-1.55) | 1.43 (1.33-1.55) | 1.43 (1.33-1.55) | 1.43 (1.33-1.55) | 1.21 (1.18-1.24) | 1.21 (1.06-1.24) | 1.22 (1.11-1.24) | 1.22 (1.11-1.24) |
| Japanese | 1.33 | 1.33 | 1.33 | 1.33 | 1.33 | 0.74 | 0.79 | 0.79 |
| Korean | 1.86 | 1.86 | 1.86 | 1.86 | 1.87 | 0.93 | 1.02 | 1.02 |
| Punjabi | 3.90 | 3.90 | 3.90 | 3.90 | 3.90 | 0.96 | 1.09 | 1.09 |
| Russian | 1.74 | 1.74 | 1.74 | 1.74 | 1.74 | 1.05 | 1.06 | 1.06 |
| Thai | 2.39 | 2.39 | 2.39 | 2.39 | 2.39 | 0.77 | 0.83 | 0.83 |
| code | 1.54 (1.46-1.69) | 1.54 (1.46-1.69) | 1.54 (1.46-1.69) | 1.54 (1.46-1.69) | 1.22 (1.16-1.26) | 1.17 (1.12-1.20) | 1.19 (1.13-1.20) | 1.19 (1.13-1.20) |
| mixed | 2.04 | 2.04 | 2.04 | 2.04 | 1.55 | 1.00 | 1.00 | 1.00 |
