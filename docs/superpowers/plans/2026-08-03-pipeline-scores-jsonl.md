# Pipeline Scores JSONL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/superpowers/specs/2026-08-03-pipeline-scores-jsonl-design.md`

**Goal:** Replace Google Sheets score logging in `run_pipeline.py` with local `pipeline_scores.jsonl`, clean docs/ignore, and update open UP-02 PR #3.

**Architecture:** Keep `record_result` inline in `run_pipeline.py`. Append one JSON object per gene. Remove all Google client imports and import-time Sheets init. Move the gene loop (and annotate/compare imports) under `if __name__ == "__main__"` so the module can be imported for a focused unit test without starting a benchmark run or requiring `creds/`.

**Tech Stack:** Python stdlib (`json`, `datetime`), pytest, git worktree `upstream/UP-02-compareannotations`, `gh` for PR #3.

## Global Constraints

- Scores path: `pipeline_scores.jsonl` at repo root (JSONL append).
- Record fields: `timestamp`, `gene`, `comparison_result`, `duration`, `num_papers_used`, `num_total_papers`, `cumulative_relevance`.
- No Google Sheets / Drive / service-account code or README install steps.
- Keep `creds/` in `.gitignore`; also ignore `pipeline_scores.jsonl`, `completed_genes.txt`, `error_log.txt`.
- Update fork `master` and force-update UP-02 branch so PR #3 has no Sheets dependency.
- No `git add .` / `git add -A` on UP-02 — named paths only.
- Do not delete local `creds/` on disk; do not migrate historical sheet rows; no CLI path override.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `run_pipeline.py` | Modify | JSONL `record_result`; remove Google; `__main__` guard |
| `tests/test_run_pipeline_scores.py` | Create | Unit test for JSONL append |
| `.gitignore` | Modify | Ignore pipeline run artifacts |
| `README.md` | Modify | Drop Google Sheets/creds docs |
| `docs/superpowers/specs/2026-07-21-upstream-pr-queue-design.md` | Modify | UP-02 note: no Sheets |
| `.worktrees/UP-02-compareannotations/run_pipeline.py` | Modify | Same JSONL end-state as master |
| `.worktrees/UP-02-compareannotations/.gitignore` | Modify | Ignore run artifacts (+ keep `creds/` if useful) |

---

### Task 1: JSONL `record_result` + import-safe harness

**Files:**
- Modify: `run_pipeline.py`
- Create: `tests/test_run_pipeline_scores.py`

**Interfaces:**
- Consumes: none (stdlib only for scoring I/O)
- Produces: `SCORES_LOG = "pipeline_scores.jsonl"`; `record_result(gene, comparison_result, duration, num_papers_used, num_total_papers, cumulative_relevance=0.0) -> None` appends one JSON line

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_pipeline_scores.py`:

```python
import json
from pathlib import Path

import run_pipeline


def test_record_result_appends_jsonl(tmp_path, monkeypatch):
    scores = tmp_path / "pipeline_scores.jsonl"
    monkeypatch.setattr(run_pipeline, "SCORES_LOG", str(scores))

    run_pipeline.record_result(
        "Rv0001",
        {"score": 0.9},
        12.5,
        3,
        10,
        1.25,
    )
    run_pipeline.record_result("Rv0002", "N/A", "N/A", 0, "N/A")

    lines = scores.read_text().strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["gene"] == "Rv0001"
    assert first["comparison_result"] == {"score": 0.9}
    assert first["duration"] == 12.5
    assert first["num_papers_used"] == 3
    assert first["num_total_papers"] == 10
    assert first["cumulative_relevance"] == 1.25
    assert "timestamp" in first

    second = json.loads(lines[1])
    assert second["gene"] == "Rv0002"
    assert second["comparison_result"] == "N/A"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_pipeline_scores.py::test_record_result_appends_jsonl -v`

Expected: FAIL — either import error from missing Google packages / missing `creds/`, or `AttributeError: SCORES_LOG`, or `record_result` still talking to Sheets.

- [ ] **Step 3: Rewrite `run_pipeline.py`**

Replace the file contents with:

```python
"""
run with:

python -m run_pipeline 2>&1 | tee log.txt

"""

# Manual evaluation harness (not the normal app entry point). Runs a fixed
# benchmark gene list, compares generated JSON against trusted fixtures, and
# appends scores to pipeline_scores.jsonl.
import json
import time
import os
from datetime import datetime
import traceback

COMPLETE_LOG = "completed_genes.txt"
ERROR_LOG = "error_log.txt"
SCORES_LOG = "pipeline_scores.jsonl"


def record_result(
    gene,
    comparison_result,
    duration,
    num_papers_used,
    num_total_papers,
    cumulative_relevance=0.0,
):
    record = {
        "timestamp": datetime.now().isoformat(),
        "gene": gene,
        "comparison_result": comparison_result,
        "duration": duration,
        "num_papers_used": num_papers_used,
        "num_total_papers": num_total_papers,
        "cumulative_relevance": cumulative_relevance,
    }
    with open(SCORES_LOG, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Score recorded: {gene}")


def mark_complete(gene):
    with open(COMPLETE_LOG, "a") as f:
        f.write(gene + "\n")
    print(f"Completed {gene}")


def log_error(gene, error):
    timestamp = datetime.now().isoformat()
    error_message = (
        f"\n[{timestamp}] ERROR processing {gene}\n"
        f"{str(error)}\n"
        f"{traceback.format_exc()}\n"
        f"{'='*60}\n"
    )
    with open(ERROR_LOG, "a") as f:
        f.write(error_message)
    print(f"Error processing {gene}")
    print(error)


def load_completed_genes():
    if not os.path.exists(COMPLETE_LOG):
        return set()
    with open(COMPLETE_LOG, "r") as f:
        return set(line.strip() for line in f)


GENES = [
    "Rv0001",
    "Rv0002",
    "Rv0003",
    "Rv2007c",
    "Rv2057c",
    "Rv2070c",
    "Rv2418c",
    "Rv2612c",
    "Rv3221A",
    "Rv3459c",
]


def main():
    from autoannotation.__main__ import main as annotate
    from compareannotations.__main__ import main as compare

    completed_genes = load_completed_genes()
    # completed_genes.txt makes long benchmark runs resumable after model/API
    # failures; deleting it intentionally reruns the full fixed list.
    for gene in GENES:
        if gene in completed_genes:
            print(f"Skipping {gene}: already completed")
            continue
        try:
            print(f"\nStarting {gene}")
            start = time.time()
            annotation_result = annotate(gene)
            if annotation_result is None:
                print(f"Skipping {gene}: annotation failed")
                record_result(gene, "N/A", "N/A", 0, "N/A")
                continue
            papers_used = annotation_result["papers_used"]
            total_papers = annotation_result["all_papers"]
            generated_json = annotation_result["output_path"]
            cumulative_relevance = annotation_result["cumulative_relevance"]
            trusted_json = os.path.join("trust_json", f"trust_{gene}.json")
            duration = time.time() - start
            print(f"\nComparing {gene}: {trusted_json} vs {generated_json}")
            comparison_result = compare(trusted_json, generated_json)
            record_result(
                gene,
                comparison_result,
                duration,
                len(papers_used),
                len(total_papers),
                cumulative_relevance,
            )
            mark_complete(gene)
        except Exception as e:
            log_error(gene, e)
            continue


if __name__ == "__main__":
    main()
```

Notes:
- Do **not** leave Google imports, spreadsheet IDs, or service-account paths.
- Lazy-import annotate/compare inside `main()` so the unit test can import `run_pipeline` without loading the annotation stack.
- Preserve the paper-count comment block above `GENES` if still useful locally; optional — omit to keep the file lean (either is fine).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_pipeline_scores.py::test_record_result_appends_jsonl -v`

Expected: PASS

Also confirm no Google imports remain:

Run: `rg -n 'google|spreadsheet|SERVICE_ACCOUNT|creds/' run_pipeline.py`

Expected: no matches

- [ ] **Step 5: Commit**

```bash
git add run_pipeline.py tests/test_run_pipeline_scores.py
git commit -m "$(cat <<'EOF'
feat: log run_pipeline scores to local JSONL

Drop Google Sheets/service-account logging so the benchmark harness needs no creds.
EOF
)"
```

---

### Task 2: README + `.gitignore` cleanup on master

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 1 behavior (`pipeline_scores.jsonl`)
- Produces: docs/ignore matching the JSONL harness with no Google install path

- [ ] **Step 1: Update `.gitignore`**

Keep existing `creds/`. After the `creds/` block (or nearby with other local artifacts), ensure these lines exist:

```
pipeline_scores.jsonl
completed_genes.txt
error_log.txt
```

Do not remove `creds/`.

- [ ] **Step 2: Update README.md**

Make these exact content edits:

1. In the repo layout list, change the `run_pipeline.py` bullet from Google Sheets logging to local JSONL, e.g.:

```markdown
- `run_pipeline.py`: manual benchmark script for a fixed MTB gene list; appends scores to `pipeline_scores.jsonl`.
```

2. Delete the entire block that says `run_pipeline.py` additionally requires Google client libraries, including the `pip install google-auth google-api-python-client` fence.

3. In “Local/generated assets”, replace or remove the bullet that says `creds/` is only needed for the Google Sheets benchmark script. Prefer:

```markdown
- `pipeline_scores.jsonl`, `completed_genes.txt`, and `error_log.txt` are local `run_pipeline.py` run artifacts (gitignored).
- `creds/` remains gitignored for any local secrets; it is not required by the benchmark harness.
```

- [ ] **Step 3: Verify docs no longer push Google for the harness**

Run: `rg -n 'google-auth|google-api-python-client|Google Sheets|service-account' README.md`

Expected: no matches (or only unrelated mentions if any exist elsewhere — there should be none for Sheets).

Run: `rg -n 'pipeline_scores|completed_genes|error_log' .gitignore`

Expected: all three filenames present.

- [ ] **Step 4: Commit**

```bash
git add README.md .gitignore
git commit -m "$(cat <<'EOF'
docs: drop Sheets setup; ignore pipeline score artifacts

Align README and gitignore with local JSONL score logging.
EOF
)"
```

---

### Task 3: Queue note + UP-02 PR #3 sync

**Files:**
- Modify: `docs/superpowers/specs/2026-07-21-upstream-pr-queue-design.md` (on master; force-add if `docs/` is ignored)
- Modify: `.worktrees/UP-02-compareannotations/run_pipeline.py`
- Modify: `.worktrees/UP-02-compareannotations/.gitignore`

**Interfaces:**
- Consumes: Task 1 end-state `run_pipeline.py`; Task 2 ignore patterns
- Produces: UP-02 branch/PR without Google Sheets; queue notes updated

- [ ] **Step 1: Update UP-02 notes in the queue doc on master**

In `docs/superpowers/specs/2026-07-21-upstream-pr-queue-design.md`, under `### UP-02 — Add annotation comparison scoring harness`, update **Notes** (and leave Status `open`) to state there is no Google Sheets/creds dependency and scores go to `pipeline_scores.jsonl`. Example notes text:

```markdown
- **Notes:** Do not upstream large generated JSON corpora. Stacked on UP-01. `run_pipeline.py` appends scores to local `pipeline_scores.jsonl` (no Google Sheets/service-account dependency).
```

- [ ] **Step 2: Commit queue note on master**

```bash
git add -f docs/superpowers/specs/2026-07-21-upstream-pr-queue-design.md
git commit -m "$(cat <<'EOF'
docs: note UP-02 uses local JSONL scores, not Sheets

EOF
)"
```

- [ ] **Step 3: Copy JSONL `run_pipeline.py` into the UP-02 worktree**

From repo root:

```bash
cp run_pipeline.py .worktrees/UP-02-compareannotations/run_pipeline.py
```

Then edit `.worktrees/UP-02-compareannotations/.gitignore` so it contains at least:

```
__pycache__/**
.cache/**
**/*.pyc
creds/
pipeline_scores.jsonl
completed_genes.txt
error_log.txt
```

UP-02’s README is Ethan’s stub and does not mention Google Sheets — leave it unchanged unless a Sheets mention appears.

- [ ] **Step 4: Verify UP-02 tree has no Google wiring**

Run:

```bash
rg -n 'google|spreadsheet|SERVICE_ACCOUNT|creds/' .worktrees/UP-02-compareannotations/run_pipeline.py
rg -n 'pipeline_scores|completed_genes|error_log|creds/' .worktrees/UP-02-compareannotations/.gitignore
```

Expected: no Google matches in `run_pipeline.py`; ignore patterns present.

- [ ] **Step 5: Commit on the UP-02 branch (named paths only)**

```bash
cd .worktrees/UP-02-compareannotations
git status -sb
git add run_pipeline.py .gitignore
git commit -m "$(cat <<'EOF'
fix: log pipeline scores to JSONL instead of Sheets

Remove service-account Sheets logging from the compare harness so review needs no Google creds.
EOF
)"
```

Prefer a new commit on the branch (do not amend the already-pushed UP-02 tip unless the user explicitly asks).

- [ ] **Step 6: Push UP-02 and confirm PR #3**

```bash
git push origin upstream/UP-02-compareannotations
gh pr view 3 --repo ethanbustad/gene-autoannotator --json url,title,headRefName,commits
```

Expected: PR URL still https://github.com/ethanbustad/gene-autoannotator/pull/3; latest commit message mentions JSONL / Sheets removal.

Optional PR comment:

```bash
gh pr comment 3 --repo ethanbustad/gene-autoannotator --body "$(cat <<'EOF'
Updated `run_pipeline.py` to append benchmark scores to local `pipeline_scores.jsonl` instead of Google Sheets. No service-account credentials are required to review or run the harness.
EOF
)"
```

- [ ] **Step 7: Return to master and sanity-check**

```bash
cd /home/caden-saltzberg/projects/sch/gene-autoannotator
rg -n 'google\.oauth2|googleapiclient|SPREADSHEET|SERVICE_ACCOUNT' run_pipeline.py .worktrees/UP-02-compareannotations/run_pipeline.py
pytest tests/test_run_pipeline_scores.py -v
```

Expected: no Google matches; test PASS.

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| JSONL append with sheet-equivalent fields + timestamp | Task 1 |
| Remove Google imports/creds/spreadsheet IDs | Task 1 |
| Keep call sites / resume via `completed_genes.txt` | Task 1 |
| README drop Google install/creds Sheets guidance | Task 2 |
| Keep `creds/` ignored; ignore scores + pipeline logs | Task 2 |
| UP-02 queue note | Task 3 |
| Update UP-02 branch/PR #3 | Task 3 |
| No historical sheet migration / no path CLI / no ScoresSink | (non-goals; omitted) |

## Self-review notes

- No TBD/placeholder steps.
- `record_result` signature matches Task 1 test and call sites.
- UP-02 README intentionally untouched (no Sheets mentions there).
- Force-add only for ignored `docs/` queue file on master.
