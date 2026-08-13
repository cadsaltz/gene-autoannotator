# Env-Authoritative Fleet Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Spec:** `docs/superpowers/specs/2026-08-13-env-authoritative-fleet-settings-design.md`

**Goal:** Make operator fleet knobs env-file truth (no tier/runtime invent-or-override), and add `AUTOANNOTATION_SECTION_CHUNKING` so operators can restore July-style full-section prompts for context A/B tests.

**Architecture:** Extend worker fleet ensure with `ensure_operator_env` that write-if-misses slot ctx / keep-alive / max-loaded / chunking into `worker.env`, then reloads into `os.environ`. Serve/bench stop applying `_job_keep_alive_for_tier`. Context total is always `OLLAMA_FLEET_SLOT_CTX × OLLAMA_FLEET_PARALLEL` from env (ignore `OLLAMA_CONTEXT_LENGTH` as an operator override). Pipeline gates `expand_sections` on the chunking flag.

**Tech Stack:** Python 3, pytest, existing `shared.env_persist`, `worker/fleet/setup.py`, `autoannotation/section_chunking.py`.

## Global Constraints

- Env file is truth after ensure; never invent keep-alive, slot ctx, max-loaded, or chunking at call time without a prior write to `worker.env`.
- VRAM tier may stay dynamic for warnings/dashboard; tier must never override keep-alive or max-loaded once those keys exist in the env file.
- Missing-key policy: prompt for servers/parallel/slots/budget (existing); write defaults for slot ctx / keep-alive / max-loaded / chunking.
- Context: only `OLLAMA_FLEET_SLOT_CTX` is the operator knob; total = slot × parallel.
- Keep-alive: only `OLLAMA_FLEET_KEEP_ALIVE`; always copy to `AUTOANNOTATION_OLLAMA_KEEP_ALIVE`.
- Max-loaded write-if-missing: `model_count` if tier `warm_stack` else `1` (once).
- Chunking: `AUTOANNOTATION_SECTION_CHUNKING` default `true`; `false` = identity expand (July behavior).
- Invalid ints / unparsable chunking flag after materialize → raise with key name (no silent fallback).
- TDD; no `git add .` / `git add -A` — named paths only.

## File map

| Path | Action | Responsibility |
|------|--------|----------------|
| `worker/fleet/setup.py` | Modify | `ensure_operator_env`, env-only context/max-loaded, stop inventing |
| `worker/serve.py` | Modify | Stop tier keep-alive / max-loaded overwrite |
| `worker/bench.py` | Modify | Same; keep CLI `--keep-alive` as write-to-env then read |
| `autoannotation/section_chunking.py` | Modify | Parse chunking flag; optional persist helper |
| `autoannotation/autoannotation.py` | Modify | Gate expand on flag |
| `worker.env.example` | Modify | Document knobs as env-as-truth |
| `USAGE.md` / `worker/README.md` | Modify | Document slot ctx, keep-alive, chunking |
| `tests/test_operator_env.py` | Create | Materialize + no-override tests |
| `tests/test_fleet_setup.py` | Modify | Context/max-loaded expectations |
| `tests/test_section_chunking.py` | Modify | Flag parse + disable |
| `tests/test_section_chunking_wireup.py` | Modify | Disabled expand is identity |

---

### Task 1: Section chunking env flag (parse + wire-up)

**Files:**
- Modify: `autoannotation/section_chunking.py`
- Modify: `autoannotation/autoannotation.py`
- Modify: `tests/test_section_chunking.py`
- Modify: `tests/test_section_chunking_wireup.py`

**Interfaces:**
- Consumes: existing `expand_sections`, `excerpt_max_chars_from_env`
- Produces:
  - `CHUNKING_ENV = "AUTOANNOTATION_SECTION_CHUNKING"`
  - `parse_section_chunking_flag(raw: str) -> bool` (raises `ValueError` on bad values)
  - `section_chunking_enabled(*, environ: Mapping[str, str] | None = None) -> bool` — if key missing → `True` (persist is Task 2 / worker path); if present → parse
  - `_sections_for_extraction` respects enabled flag

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_section_chunking.py (add)
import pytest
from autoannotation.section_chunking import (
    parse_section_chunking_flag,
    section_chunking_enabled,
)


def test_parse_section_chunking_flag_truthy_falsy():
    for raw in ("1", "true", "TRUE", "yes", "on"):
        assert parse_section_chunking_flag(raw) is True
    for raw in ("0", "false", "FALSE", "no", "off"):
        assert parse_section_chunking_flag(raw) is False


def test_parse_section_chunking_flag_invalid():
    with pytest.raises(ValueError, match="AUTOANNOTATION_SECTION_CHUNKING"):
        parse_section_chunking_flag("maybe")


def test_section_chunking_enabled_defaults_true_when_unset():
    assert section_chunking_enabled(environ={}) is True


def test_section_chunking_enabled_reads_env():
    assert section_chunking_enabled(environ={"AUTOANNOTATION_SECTION_CHUNKING": "false"}) is False
```

```python
# tests/test_section_chunking_wireup.py (add)
from autoannotation.autoannotation import _sections_for_extraction


def test_sections_for_extraction_skips_expand_when_chunking_disabled(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_SECTION_CHUNKING", "false")
    p1 = "A" * 60
    p2 = "B" * 60
    fat = f"{p1}\n\n{p2}"
    pm = FakePaperManager({"1": fat})
    sections = _sections_for_extraction(pm, "1", max_chars=100)
    assert sections == [("results", fat)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_section_chunking.py tests/test_section_chunking_wireup.py -v`
Expected: FAIL — `parse_section_chunking_flag` / `section_chunking_enabled` missing; wireup still expands when disabled.

- [ ] **Step 3: Implement flag helpers + gate expand**

In `autoannotation/section_chunking.py`:

```python
CHUNKING_ENV = "AUTOANNOTATION_SECTION_CHUNKING"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def parse_section_chunking_flag(raw: str) -> bool:
    normalized = str(raw).strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise ValueError(
        f"Invalid {CHUNKING_ENV}={raw!r}; expected one of "
        f"{sorted(_TRUTHY | _FALSY)}"
    )


def section_chunking_enabled(*, environ: Mapping[str, str] | None = None) -> bool:
    if environ is None:
        environ = os.environ
    raw = environ.get(CHUNKING_ENV, "")
    if not str(raw).strip():
        return True
    return parse_section_chunking_flag(raw)
```

In `autoannotation/autoannotation.py` `_sections_for_extraction`:

```python
def _sections_for_extraction(paper_manager, pmc_id, *, max_chars):
    raw_sections = collect_paper_sections(paper_manager, pmc_id)
    from .section_chunking import section_chunking_enabled
    if not section_chunking_enabled():
        return raw_sections
    return expand_sections(raw_sections, max_chars=max_chars)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_section_chunking.py tests/test_section_chunking_wireup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add autoannotation/section_chunking.py autoannotation/autoannotation.py \
  tests/test_section_chunking.py tests/test_section_chunking_wireup.py
git commit -m "feat(autoannotation): gate section chunking on env flag"
```

---

### Task 2: `ensure_operator_env` write-if-missing for fleet knobs + chunking

**Files:**
- Modify: `worker/fleet/setup.py`
- Create: `tests/test_operator_env.py`

**Interfaces:**
- Consumes: `load_env_file`, `save_env_file`, `_default_env_path`, `FleetConfig.memory_tier`, `models.required_model_names`
- Produces:
  - `ensure_operator_env(*, env_path: Path, memory_tier: str, model_count: int) -> None`
  - Writes missing keys then sets `os.environ` from file for those keys
  - Keys + defaults:
    - `OLLAMA_FLEET_SLOT_CTX` → `"8192"`
    - `OLLAMA_FLEET_KEEP_ALIVE` → `"0"`
    - `OLLAMA_MAX_LOADED_MODELS` → `str(model_count)` if `memory_tier == "warm_stack"` else `"1"`
    - `AUTOANNOTATION_SECTION_CHUNKING` → `"true"`
  - After keep-alive materialize: always `os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = fleet keep-alive value`
  - Does not overwrite keys already present in the **file**

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_operator_env.py
from pathlib import Path

from shared.env_persist import load_env_file
from worker.fleet import setup


def test_ensure_operator_env_writes_defaults_once(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("COORDINATOR_URL=http://x\n", encoding="utf-8")
    monkeypatch.delenv("OLLAMA_FLEET_SLOT_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_FLEET_KEEP_ALIVE", raising=False)
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    monkeypatch.delenv("AUTOANNOTATION_SECTION_CHUNKING", raising=False)

    setup.ensure_operator_env(
        env_path=env_path, memory_tier="vram_overflow", model_count=5,
    )
    saved = load_env_file(env_path)
    assert saved["OLLAMA_FLEET_SLOT_CTX"] == "8192"
    assert saved["OLLAMA_FLEET_KEEP_ALIVE"] == "0"
    assert saved["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert saved["AUTOANNOTATION_SECTION_CHUNKING"] == "true"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "0"

    env_path.write_text(
        "\n".join(
            [
                "COORDINATOR_URL=http://x",
                "OLLAMA_FLEET_SLOT_CTX=2048",
                "OLLAMA_FLEET_KEEP_ALIVE=-1",
                "OLLAMA_MAX_LOADED_MODELS=3",
                "AUTOANNOTATION_SECTION_CHUNKING=false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.ensure_operator_env(
        env_path=env_path, memory_tier="warm_stack", model_count=5,
    )
    saved = load_env_file(env_path)
    assert saved["OLLAMA_FLEET_SLOT_CTX"] == "2048"
    assert saved["OLLAMA_FLEET_KEEP_ALIVE"] == "-1"
    assert saved["OLLAMA_MAX_LOADED_MODELS"] == "3"
    assert saved["AUTOANNOTATION_SECTION_CHUNKING"] == "false"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "-1"


def test_ensure_operator_env_max_loaded_warm_stack(tmp_path, monkeypatch):
    env_path = tmp_path / "worker.env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    setup.ensure_operator_env(
        env_path=env_path, memory_tier="warm_stack", model_count=4,
    )
    assert load_env_file(env_path)["OLLAMA_MAX_LOADED_MODELS"] == "4"
```

(Add `import os` at top of test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_operator_env.py -v`
Expected: FAIL — `ensure_operator_env` missing

- [ ] **Step 3: Implement `ensure_operator_env`**

```python
# worker/fleet/setup.py
OPERATOR_ENV_DEFAULTS = {
    "OLLAMA_FLEET_SLOT_CTX": "8192",
    "OLLAMA_FLEET_KEEP_ALIVE": "0",
    "AUTOANNOTATION_SECTION_CHUNKING": "true",
}


def ensure_operator_env(
    *,
    env_path: Path,
    memory_tier: str,
    model_count: int,
) -> None:
    saved = load_env_file(env_path)
    changed = False

    def _ensure(key: str, default: str) -> None:
        nonlocal changed
        if key not in saved or not str(saved.get(key, "")).strip():
            saved[key] = default
            changed = True

    _ensure("OLLAMA_FLEET_SLOT_CTX", OPERATOR_ENV_DEFAULTS["OLLAMA_FLEET_SLOT_CTX"])
    _ensure("OLLAMA_FLEET_KEEP_ALIVE", OPERATOR_ENV_DEFAULTS["OLLAMA_FLEET_KEEP_ALIVE"])
    _ensure(
        "AUTOANNOTATION_SECTION_CHUNKING",
        OPERATOR_ENV_DEFAULTS["AUTOANNOTATION_SECTION_CHUNKING"],
    )
    max_loaded_default = (
        str(max(1, int(model_count)))
        if memory_tier == "warm_stack" and model_count > 0
        else "1"
    )
    _ensure("OLLAMA_MAX_LOADED_MODELS", max_loaded_default)

    if changed:
        save_env_file(env_path, saved)

    for key in (
        "OLLAMA_FLEET_SLOT_CTX",
        "OLLAMA_FLEET_KEEP_ALIVE",
        "OLLAMA_MAX_LOADED_MODELS",
        "AUTOANNOTATION_SECTION_CHUNKING",
    ):
        os.environ[key] = saved[key]
    os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = saved["OLLAMA_FLEET_KEEP_ALIVE"]
```

Call it at the end of `ensure_fleet_config` (after `_apply_fleet_to_environ`) and also after first-time `_persist_fleet_config`, using `cfg.memory_tier` and `len(models.required_model_names())` (or `cfg.model_count` if set).

Also call from `refresh_fleet_footprints` return path only to re-sync `AUTOANNOTATION_OLLAMA_KEEP_ALIVE` from file keep-alive — **do not** rewrite max-loaded/keep-alive defaults when keys exist.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operator_env.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/fleet/setup.py tests/test_operator_env.py
git commit -m "feat(worker): materialize operator fleet knobs into worker.env"
```

---

### Task 3: Context length and max-loaded read only from env

**Files:**
- Modify: `worker/fleet/setup.py` (`effective_ollama_context_length`, `effective_max_loaded_models`, `_build_ollama_server_env`)
- Modify: `tests/test_fleet_setup.py`

**Interfaces:**
- Consumes: materialized `OLLAMA_FLEET_SLOT_CTX`, `OLLAMA_MAX_LOADED_MODELS`
- Produces:
  - `effective_ollama_context_length(*, parallel: int) -> int` = `int(SLOT_CTX) * max(1, parallel)`; **ignore** `OLLAMA_CONTEXT_LENGTH` env as operator override; raise if slot ctx missing/invalid
  - `effective_max_loaded_models(cfg, ...) -> int` = require env `OLLAMA_MAX_LOADED_MODELS` (raise if missing/invalid); ignore tier fallback and `max_loaded=` invent path unless it only mirrors env

- [ ] **Step 1: Rewrite failing/updated tests**

Replace / update in `tests/test_fleet_setup.py`:

```python
def test_build_ollama_server_env_uses_slot_ctx_times_parallel(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_FLEET_SLOT_CTX", "8192")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "99999")  # must be ignored
    env = setup._build_ollama_server_env(port=11435, parallel=2, gpu_index=0)
    assert env["OLLAMA_CONTEXT_LENGTH"] == "16384"


def test_effective_ollama_context_length_requires_slot_ctx(monkeypatch):
    monkeypatch.delenv("OLLAMA_FLEET_SLOT_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    import pytest
    with pytest.raises(ValueError, match="OLLAMA_FLEET_SLOT_CTX"):
        setup.effective_ollama_context_length(parallel=2)


def test_effective_ollama_context_length_scales_with_parallel(monkeypatch):
    monkeypatch.setenv("OLLAMA_FLEET_SLOT_CTX", "8192")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "1")  # ignored
    assert setup.effective_ollama_context_length(parallel=2) == 16384
    assert setup.effective_ollama_context_length(parallel=1) == 8192


def test_effective_max_loaded_models_requires_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_MAX_LOADED_MODELS", raising=False)
    cfg = FleetConfig(
        num_servers=1, parallel=1, max_slots=1,
        memory_tier="warm_stack", model_count=4,
    )
    import pytest
    with pytest.raises(ValueError, match="OLLAMA_MAX_LOADED_MODELS"):
        setup.effective_max_loaded_models(cfg)


def test_effective_max_loaded_models_reads_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MAX_LOADED_MODELS", "2")
    cfg = FleetConfig(num_servers=1, parallel=1, max_slots=1, memory_tier="swap")
    assert setup.effective_max_loaded_models(cfg) == 2
```

Delete obsolete tests that expect inventing 8192 without env, respecting `OLLAMA_CONTEXT_LENGTH` override, or tier fallback when env unset:
- `test_effective_ollama_context_length_respects_explicit_total`
- `test_effective_max_loaded_models_defaults_to_model_count_for_swap_tier`
- `test_effective_max_loaded_models_uses_model_count_for_warm_stack`
(or rewrite them to match env-only behavior)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fleet_setup.py -k "context_length or max_loaded or build_ollama_server_env" -v`
Expected: FAIL against old invent/override behavior

- [ ] **Step 3: Implement env-only readers**

```python
def effective_ollama_context_length(*, parallel: int) -> int:
    raw = os.environ.get("OLLAMA_FLEET_SLOT_CTX", "").strip()
    if not raw:
        raise ValueError(
            "OLLAMA_FLEET_SLOT_CTX is required in the environment "
            "(call ensure_operator_env / ensure_fleet_config first)"
        )
    try:
        slot = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid OLLAMA_FLEET_SLOT_CTX={raw!r}") from exc
    if slot < 1:
        raise ValueError(f"Invalid OLLAMA_FLEET_SLOT_CTX={raw!r}")
    return slot * max(1, int(parallel))


def effective_max_loaded_models(
    cfg: FleetConfig,
    *,
    max_loaded: int | None = None,
) -> int:
    raw = os.environ.get("OLLAMA_MAX_LOADED_MODELS", "").strip()
    if not raw:
        raise ValueError(
            "OLLAMA_MAX_LOADED_MODELS is required in the environment "
            "(call ensure_operator_env / ensure_fleet_config first)"
        )
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid OLLAMA_MAX_LOADED_MODELS={raw!r}") from exc
    if value < 1:
        raise ValueError(f"Invalid OLLAMA_MAX_LOADED_MODELS={raw!r}")
    return value
```

Keep `_build_ollama_server_env` setting child `OLLAMA_CONTEXT_LENGTH` to `str(effective_ollama_context_length(parallel=parallel))` (computed for the Ollama process only — not an operator file key).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fleet_setup.py tests/test_operator_env.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/fleet/setup.py tests/test_fleet_setup.py
git commit -m "fix(worker): read context and max_loaded only from env"
```

---

### Task 4: Stop serve/bench tier overrides of keep-alive and max-loaded

**Files:**
- Modify: `worker/serve.py`
- Modify: `worker/bench.py`
- Modify: `tests/test_operator_env.py` (add serve-path style unit if easy) or a small `tests/test_serve_keep_alive_env.py`

**Interfaces:**
- Consumes: `ensure_fleet_config` → `ensure_operator_env` already synced keep-alive
- Produces: serve/bench no longer call `_job_keep_alive_for_tier` to overwrite env; no `os.environ.pop("OLLAMA_MAX_LOADED_MODELS")` before recompute

- [ ] **Step 1: Write the failing test**

```python
# tests/test_operator_env.py (add)
def test_apply_fleet_keep_alive_does_not_use_tier_when_file_set(tmp_path, monkeypatch):
    """Simulate post-ensure: file keep-alive must survive a would-be tier default."""
    env_path = tmp_path / "worker.env"
    env_path.write_text(
        "\n".join(
            [
                "OLLAMA_FLEET_SERVERS=1",
                "OLLAMA_FLEET_PARALLEL=1",
                "WORKER_MAX_SLOTS=1",
                "OLLAMA_FLEET_KEEP_ALIVE=-1",
                "OLLAMA_FLEET_SLOT_CTX=2048",
                "OLLAMA_MAX_LOADED_MODELS=1",
                "AUTOANNOTATION_SECTION_CHUNKING=true",
                "OLLAMA_FLEET_W_ALL_BYTES=1000",
                "OLLAMA_FLEET_W_PEAK_BYTES=1000",
                "OLLAMA_FLEET_C_SLOT_BYTES=1",
                "OLLAMA_FLEET_MEMORY_TIER=vram_overflow",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OLLAMA_FLEET_KEEP_ALIVE", "-1")
    # After ensure_operator_env, sync must keep -1 even for overflow tier
    setup.ensure_operator_env(
        env_path=env_path, memory_tier="vram_overflow", model_count=5,
    )
    assert os.environ["OLLAMA_FLEET_KEEP_ALIVE"] == "-1"
    assert os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] == "-1"
```

Manually remove from `worker/serve.py` and `worker/bench.py` the blocks that:

```python
os.environ.pop("OLLAMA_MAX_LOADED_MODELS", None)
...
job_keep_alive = _job_keep_alive_for_tier(...)
os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = ...
os.environ["OLLAMA_FLEET_KEEP_ALIVE"] = ...
```

Replace with reading already-materialized env:

```python
max_loaded = effective_max_loaded_models(fleet)
# do not pop env
keep_alive = os.environ["OLLAMA_FLEET_KEEP_ALIVE"]
os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = keep_alive
fleet = replace(fleet, keep_alive=keep_alive)
```

For bench `--keep-alive` CLI: if provided, write that value into `worker.env` `OLLAMA_FLEET_KEEP_ALIVE`, then `ensure_operator_env` / re-read (CLI becomes a write, not a silent process-only override). Minimal approach:

```python
if getattr(args, "keep_alive", None):
    path = default_env_path()
    saved = load_env_file(path)
    saved["OLLAMA_FLEET_KEEP_ALIVE"] = str(args.keep_alive).strip()
    save_env_file(path, saved)
    os.environ["OLLAMA_FLEET_KEEP_ALIVE"] = saved["OLLAMA_FLEET_KEEP_ALIVE"]
    os.environ["AUTOANNOTATION_OLLAMA_KEEP_ALIVE"] = saved["OLLAMA_FLEET_KEEP_ALIVE"]
```

Remove unused `_job_keep_alive_for_tier` imports from serve; keep the helper in bench only if still used for CLI default suggestion — otherwise delete or leave unused and unused-import clean.

Also fix `_fleet_from_env` / `_normalize_fleet_config` so keep-alive never falls back to `sizing.TIER_KEEP_ALIVE[...]` when the key is missing — `ensure_operator_env` must run before `_fleet_from_env` reads keep-alive, **or** `_fleet_from_env` requires the key. Preferred order in `ensure_fleet_config`:

1. Existing sizing ensure / load cfg / normalize tier  
2. `ensure_operator_env(...)` using normalized tier + model_count  
3. Re-read keep-alive from env into `cfg = replace(cfg, keep_alive=os.environ["OLLAMA_FLEET_KEEP_ALIVE"])`  
4. `_apply_fleet_to_environ`  
5. Never assign tier keep-alive over file

- [ ] **Step 2: Run relevant tests**

Run: `python -m pytest tests/test_operator_env.py tests/test_fleet_setup.py -v`
Expected: failures until serve/bench/setup order fixed

- [ ] **Step 3: Implement serve/bench/setup order fixes**

Edit `worker/serve.py` and `worker/bench.py` as above; reorder `ensure_fleet_config` to materialize operator knobs after tier is known and before returning; strip tier keep-alive fallback from `_fleet_from_env` (require key or call ensure first).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operator_env.py tests/test_fleet_setup.py tests/test_section_chunking.py tests/test_section_chunking_wireup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add worker/serve.py worker/bench.py worker/fleet/setup.py tests/test_operator_env.py
git commit -m "fix(worker): never let VRAM tier override env keep-alive or max_loaded"
```

---

### Task 5: Docs + env example

**Files:**
- Modify: `worker.env.example`
- Modify: `USAGE.md`
- Modify: `worker/README.md`

**Interfaces:**
- Consumes: finalized key names from Tasks 1–4
- Produces: operator docs matching env-as-truth

- [ ] **Step 1: Update `worker.env.example`**

Replace keep-alive / context comments with:

```bash
# Operator knobs (write-if-missing on first ensure; never overridden by VRAM tier):
# OLLAMA_FLEET_SLOT_CTX=8192
# OLLAMA_FLEET_KEEP_ALIVE=0
# OLLAMA_MAX_LOADED_MODELS=1
# AUTOANNOTATION_SECTION_CHUNKING=true
# Managed ollama serve gets OLLAMA_CONTEXT_LENGTH = SLOT_CTX × OLLAMA_FLEET_PARALLEL
# (not an operator file key). For July-like full sections + small context A/B:
#   OLLAMA_FLEET_SERVERS=1
#   OLLAMA_FLEET_PARALLEL=1
#   WORKER_MAX_SLOTS=1
#   OLLAMA_FLEET_SLOT_CTX=2048
#   AUTOANNOTATION_SECTION_CHUNKING=false
```

Remove lines that say tier defaults overwrite keep-alive or that `OLLAMA_CONTEXT_LENGTH` is the operator override.

- [ ] **Step 2: Update USAGE.md / worker/README.md tables**

Document `OLLAMA_FLEET_SLOT_CTX`, env-authoritative keep-alive, `AUTOANNOTATION_SECTION_CHUNKING`, and that Ollama still truncates prompts that exceed slot context when chunking is off.

- [ ] **Step 3: Commit**

```bash
git add worker.env.example USAGE.md worker/README.md
git commit -m "docs: env-authoritative fleet knobs and chunking flag"
```

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Write-if-missing slot ctx / keep-alive / max-loaded / chunking | Task 2 |
| Prompt still for servers/parallel/slots/budget | unchanged ensure path + Task 2/4 order |
| Context = SLOT_CTX × PARALLEL; ignore CONTEXT_LENGTH override | Task 3 |
| Keep-alive single source + copy to AUTOANNOTATION_* | Task 2 + 4 |
| Tier never overrides keep-alive / max-loaded | Task 4 |
| Max-loaded default warm_stack→model_count else 1 once | Task 2 |
| Chunking flag default true; false = July sections | Task 1 |
| Invalid values raise | Task 1 + 3 |
| Docs / example | Task 5 |

## Placeholder / consistency self-check

- No TBD steps; function names match across tasks (`ensure_operator_env`, `section_chunking_enabled`, `OLLAMA_FLEET_SLOT_CTX`).
- Tests that currently assume inventing context/max-loaded are explicitly retired in Task 3.
