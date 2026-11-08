## Optimizer rules

Each rule is a small module in [`src/tokensaver/optimizer/`](https://github.com/behrouzbk/tokensaver/tree/main/src/tokensaver/optimizer).
**Safe** rules cannot change meaning and are applied by default. **Review** rules are shown
with their savings and applied only when you ask (`--apply all` or `--apply <rule,...>`).
Code blocks are never changed. Few-shot examples are never reworded.


Every saving is **measured**: tokensaver counts the prompt before and after each change on
the model you chose. Changes that save nothing on that model are not listed. (Safe
whitespace fixes that save 0 tokens are still applied for a tidy file, and reported in one
line.)
