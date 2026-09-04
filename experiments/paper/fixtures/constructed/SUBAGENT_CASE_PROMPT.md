# Tie-break case generation

You generate **three dummy extractor JSON objects** for one consensus trial.
Do **not** change `expected`, `expect_llm`, `case_family`, or `agreement`.

## Brief (authoritative)

```json
{BRIEF_JSON}
```

## Rules

1. Output a single JSON object with keys:
   - all brief fields unchanged (`brief_id` becomes `case_id`)
   - `candidates`: array of exactly 3 objects
2. Each candidate must contain at least `field_key` from the brief.
   - `domain=general`: `{"answer": "..."}` (optional extra keys ok but unused)
   - `domain=biology`: include `gene_id`, `name` from `identity`, plus `function` (and nulls for other biology fields if convenient)
3. Honor `agreement`:
   - `majority_mode=exact`: `majority_count` candidates use the **exact** `expected` string; minority conflicts.
   - `majority_mode=paraphrase`: `majority_count` candidates are **non-identical paraphrases** of `expected` (vary wording/order; keep shared content words); minority conflicts with different meaning.
   - `majority_mode=none`: three incompatible values; no majority; field value can be anything mutually conflicting; expected remains null.
4. If `extractor_0_is_minority` is true, `candidates[0]` must be the conflicting/wrong value.
5. For nonsense families, majority strings are made-up words/phrases (e.g. zorblin, quantex); still follow exact vs paraphrase mode.
6. Do not include source excerpts. Do not call tools. Do not explain — return JSON only.

## Output shape

```json
{
  "case_id": "<brief_id>",
  "domain": "...",
  "case_family": "...",
  "experiment_tags": [],
  "field_key": "...",
  "expect_llm": true,
  "expected": "...",
  "candidates": [{}, {}, {}],
  "notes": "..."
}
```
