# Contributing

Read [README.md](README.md) first — it's the canonical doc. The sections "Extending the grammar" and "Editing the generator" describe the contribution protocol; the "Implementation pitfalls" subsection captures known traps.

Quick reference:

- `pip install -e ".[dev]"` then `pytest` to set up.
- One grammar rule, one bug fix, or one autofix per PR.
- Every new rule needs: grammar update, autofix or validator code, a test that fails before and passes after, a `test-log.md` entry.
- The four-step protocol after any code change is in the README under "Editing the generator." Run all four steps before opening a PR.
- Cube invariants (10.8 m edge, 3×3×3 subdivision, red, 120 m grid) are Tschumi's — changes need a source citation.

CI runs `pytest` and regenerates the showcase folies on every PR. If your change regenerates the showcase, commit the updated `.glb` and validation files.
