# Task 3 report: Arm C excerpt-aware verbatim judge

Status: DONE

## Changes
- `experiments/paper/runners/consensus_arms_judge_c.py` (new): `ARM_C_JUDGE_PROMPT`, `build_arm_c_prompt`,
  `select_supported_verbatim`, `make_ollama_judge_fn` (thin live wiring, model gemma4:26b, think=False,
  schema via `_batch_consensus_schema`), `JUDGE_MODEL`.
- `experiments/paper/runners/consensus_arms_decide.py`: added `decide_arm_c`; `JUDGE_MODEL` now imported from judge_c
  (avoids circular import; `TRIO_*`/`JUDGE_MODEL` still exported from decide).
- Tests: `test_consensus_arms_judge_c.py` (new, 14), `test_consensus_arms_decide.py` (+2 arm C tests).

## Behavior
- No vote gate: all trio candidates (incl. null-filled) deep-copied and sent to `judge_fn(candidates=, field_keys=, excerpt=, gene_id=, gene_name=)`.
- Post-filter: strings exact or `token_jaccard` >= 0.85 (returns the candidate's wording, best match); arrays set-equal
  (returns the candidate list); booleans exact `bool` (no 1/"true"); null/empty/type mismatch -> None.

## Tests
`pytest experiments/paper/tests` all pass (see commit). Tests/impl were written together; red phase not separately observed.

## Concerns
- Brief names kwarg `fields` but its test uses `field_keys`; implemented `field_keys`.
- Imports private `_batch_consensus_schema` from `autoannotation.llms` (exists; production untouched).
- `token_jaccard` uses content tokens; stopword-only strings could soft-match loosely (edge case).
- `make_ollama_judge_fn` only mock-tested; not run against live Ollama.
