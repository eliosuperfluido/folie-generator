# Rationale Schema

Every guided folie emits a `<name>.rationale.json` file alongside `<name>.spec.json` and `<name>.glb`. The rationale is the paper trail of design reasoning: it is how we distinguish a Claude-authored folie from a stochastic one.

Random mode skips the rationale — the seed is the whole story.

## File format

```json
{
  "folie_name": "folie-belvedere",
  "brief": "one-line prompt this folie answers",
  "program": "belvedere | cafe | kiosk | daycare | first_aid | information | null",
  "intent": "2–3 sentences describing the design move in plain language",
  "operations_used": ["addition", "subtraction", "insertion", "repetition", "distortion", "substitution"],
  "principles_cited": ["P1", "P4", "P8"],
  "relation_to_predecessors": "how this folie varies from prior folies in the same session or set; null if first",
  "review": {
    "renders_seen": ["NE", "SW", "top", "eye"],
    "verdict": "pass | revise | fail",
    "notes": "what the renders revealed; what was revised in a v2 spec, if any"
  }
}
```

## Field rules

| Field | Required | Constraint |
|---|---|---|
| `folie_name` | yes | Matches the spec filename stem |
| `brief` | yes | ≤ 140 characters. The prompt, not the output. |
| `program` | yes | One of the Villette programs or `null`. A programless folie is valid. |
| `intent` | yes | ≤ 500 characters. Describe the move. Avoid restating the grammar. |
| `operations_used` | yes | Subset of the six canonical operations. At least one. |
| `principles_cited` | yes | One to three from `tschumi-principles.md`. Citing more than three is not rewarded. |
| `relation_to_predecessors` | yes | `null` only for the first folie in a set. Otherwise names a prior folie and the difference. |
| `review` | populated after render | Empty `{}` on first emission; filled after the feedback loop (Sprint 4). |

## What the rationale is for

- **Audit trail.** A reader of the `.spec.json` can see what the JSON encodes but not why. The rationale names the why.
- **Variation guarantee.** `relation_to_predecessors` forces each folie to differ from the last in a stated way. This is how we prevent mode collapse across a set.
- **Evaluation input.** The blind evaluation (Sprint 5) compares rationale-driven folies against random-mode folies on the same seeds. The rationale is the independent variable.
- **Commit message.** When a folie is regenerated, the diff in the rationale is more readable than the diff in the spec.

## What the rationale is NOT

- **Not a justification.** The rationale states intent; it does not defend against the grammar. The grammar is enforced mechanically.
- **Not a description of the output.** "This folie has a ramp on the south face" is a spec detail, not reasoning.
- **Not a full essay.** If the rationale exceeds ~500 characters of `intent`, the move is probably two folies pretending to be one.

## Bad rationale vs good rationale

**Bad (compliance theatre — cites every principle, describes what the JSON already says):**
```json
{
  "intent": "A folie with a ramp on the south face, a tower on the northeast corner, and two solid cells on the bottom tier. The cube frame is complete. Red material is used throughout.",
  "principles_cited": ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
}
```

**Good (names a move, commits to one or two principles, varies from the predecessor):**
```json
{
  "intent": "Heavy subtraction of the south-east column leaves the cube legible from the north but open to the promenade. The wedge on the west face registers an arrival direction.",
  "operations_used": ["subtraction", "insertion"],
  "principles_cited": ["P4", "P7"],
  "relation_to_predecessors": "folie-belvedere closed the top tier; this one opens the bottom, inverting the vertical weight."
}
```

## Workflow

See `SKILL.md` § Workflow. In guided mode, Claude writes the rationale before the spec. The spec is the execution of the rationale. If the spec cannot express the intent within the grammar, the rationale is revised first, not the grammar.

## File location

Rationale is emitted to the same directory as the spec:

```
execution/out/
├── <name>.glb
├── <name>.spec.json
└── <name>.rationale.json
```

For a field of N folies, each folie gets its own rationale. There is no set-level rationale file — variation is captured per-folie in `relation_to_predecessors`.
