# Env-Authoritative Fleet Settings + Section Chunking Flag

**Date:** 2026-08-13  
**Status:** Approved for implementation planning  
**Scope:** Make operator fleet/annotation knobs env-file truth; stop tier/runtime from inventing or overriding them; add an env kill-switch for section excerpt chunking.

## Problem

Fleet and annotation runtime still invent or override values that are not (or no longer match) `worker.env`:

- `worker serve` / `bench` overwrite `OLLAMA_FLEET_KEEP_ALIVE` and `AUTOANNOTATION_OLLAMA_KEEP_ALIVE` from VRAM tier (`_job_keep_alive_for_tier`).
- `effective_ollama_context_length` invents `parallel × 8192` without requiring `OLLAMA_FLEET_SLOT_CTX` in the env file.
- `effective_max_loaded_models` can fall back to tier/`model_count` without persisting `OLLAMA_MAX_LOADED_MODELS`.
- Section excerpt chunking (Aug 12) is always on; A/B timing vs July-style full sections needs an env flag.

Operators cannot reliably A/B context size / keep-alive / concurrency when the process silently mutates knobs.

## Goals

1. **Env file is truth** for operator fleet knobs: if a key is used at runtime, it must already be assigned in `worker.env` (after write-if-missing or interactive prompt).
2. **Dynamic tier stays dynamic** for warnings/dashboard/classification only; tier must **never** override an env operator value (especially keep-alive and max-loaded).
3. **Missing-key policy (option C):** keep interactive prompts for servers / parallel / slots / model-memory budget; for other operator knobs, write a default into `worker.env` if missing, then re-read from env/file.
4. **Section chunking kill-switch:** `AUTOANNOTATION_SECTION_CHUNKING` defaults to `true` (write-if-missing); `false` no-ops expansion so section→prompt behavior matches pre-chunking (July) for the same collected sections.

## Non-goals

- Changing fleet sizing formulas or hardware probe logic.
- Making `OLLAMA_FLEET_MEMORY_TIER` a required operator edit (tier may remain computed/refreshed).
- Persisting `OLLAMA_CONTEXT_LENGTH` as an operator knob (see Context).
- Reverting chunking code; only gating it.
- Docker/systemd redesign beyond documenting which keys must appear in the env file.

## Decisions (locked)

| Topic | Choice |
| --- | --- |
| Missing keys | Prompt for servers/parallel/slots/budget; write defaults for other operator knobs |
| Context | **Only** `OLLAMA_FLEET_SLOT_CTX` in env; total context = `SLOT_CTX × OLLAMA_FLEET_PARALLEL` |
| Keep-alive | **Only** `OLLAMA_FLEET_KEEP_ALIVE` in env; copy into `AUTOANNOTATION_OLLAMA_KEEP_ALIVE` for jobs |
| Max loaded | If missing, write recommended once: `model_count` if tier is `warm_stack`, else `1`; never rewrite unless user edits |
| Chunking | `AUTOANNOTATION_SECTION_CHUNKING` write-if-missing `true`; `false` = no-op expand |

## Design

### Architecture

Add a single **operator-env materialization** step during worker bootstrap / `ensure_fleet_config` (recommended name: `ensure_operator_env` or fold into existing ensure path):

1. Ensure sizing keys exist (existing interactive / non-interactive path).
2. For each operator knob below: if key absent from env **file**, write default; then load into `os.environ`.
3. Downstream serve/bench/fleet launch/`effective_*` **only read** materialized env values. No tier-based overwrite of keep-alive or max-loaded. No inventing slot ctx in memory without writing.

Annotation CLI / in-process jobs that do not go through worker bootstrap must still resolve chunking via the same “read env; if unset write default then read” helper when a `worker.env` / project env path is in play—or, for bare CLI without worker.env, treat unset as `true` **and** document that worker path always persists the key. Prefer one shared helper used by pipeline + worker so behavior does not diverge.

### Operator keys (must be in env before use)

| Key | Write-if-missing default | Runtime use |
| --- | --- | --- |
| `OLLAMA_FLEET_SERVERS` | prompt / existing recommend | fleet shape |
| `OLLAMA_FLEET_PARALLEL` | prompt / existing recommend | lanes + context total |
| `WORKER_MAX_SLOTS` | prompt / existing recommend | job concurrency |
| `WORKER_MODEL_MEMORY_BUDGET_GB` | prompt / existing | sizing cap (not slots) |
| `OLLAMA_FLEET_SLOT_CTX` | `8192` | per-lane context; total = slot × parallel |
| `OLLAMA_FLEET_KEEP_ALIVE` | `0` | Ollama unload policy; copied to `AUTOANNOTATION_OLLAMA_KEEP_ALIVE` |
| `OLLAMA_MAX_LOADED_MODELS` | `model_count` if current tier `warm_stack` else `1` | Ollama residency cap |
| `AUTOANNOTATION_SECTION_CHUNKING` | `true` | gate `expand_sections` |

Footprint / diagnostic keys already persisted (`OLLAMA_FLEET_W_*`, `C_SLOT`, `MEMORY_TIER`) may remain as today for sizing refresh; tier refresh must not rewrite keep-alive or max-loaded when those keys already exist in the file.

### Context length

- Remove inventing totals from a hard-coded constant without env.
- `effective_ollama_context_length(parallel)` becomes: read `OLLAMA_FLEET_SLOT_CTX` from env (required after materialize) × `max(1, parallel)` where `parallel` also comes from env/fleet config loaded from env.
- Do **not** treat `OLLAMA_CONTEXT_LENGTH` as an operator override. If present in the environment from an old file, ignore it for fleet launch (or stop documenting it); managed serve sets the process env for each `ollama serve` child to the computed total derived from slot×parallel. The operator-editable knob remains `OLLAMA_FLEET_SLOT_CTX` only.
- Document: for single-lane tests set `OLLAMA_FLEET_SERVERS=1`, `OLLAMA_FLEET_PARALLEL=1`, `WORKER_MAX_SLOTS=1`, vary `OLLAMA_FLEET_SLOT_CTX`.

### Keep-alive

- Delete or stop calling `_job_keep_alive_for_tier` from `worker/serve.py` and `worker/bench.py` for applying keep-alive.
- After materialize: `AUTOANNOTATION_OLLAMA_KEEP_ALIVE = OLLAMA_FLEET_KEEP_ALIVE` (always sync from fleet key so jobs and serve agree).
- `_normalize_fleet_config` / footprint refresh: if `OLLAMA_FLEET_KEEP_ALIVE` is in the env file, preserve it always (tier default only used when first writing the missing key).

### Max loaded

- On first materialize when key missing: compute recommended from **current** tier + `model_count`, write once.
- `effective_max_loaded_models` must return the env value only (after materialize). No silent tier fallback at call time.
- Serve/bench must not `pop` and recompute in a way that discards a file-set value; if they set process env, set it from the materialized file value.

### Section chunking flag

- Env key: `AUTOANNOTATION_SECTION_CHUNKING`
- Truthy: `1`, `true`, `yes`, `on` (case-insensitive). Falsy: `0`, `false`, `no`, `off`.
- Default when missing: write `true`, then read.
- Wire-in: `_sections_for_extraction` / `expand_sections` call site — if disabled, return `collect_paper_sections` unchanged (same labels/text as July for a given paper cache).
- Progress `sections_total` follows the (non-)expanded list.
- Document in `USAGE.md` / `worker.env.example`: set `false` for July-comparable section prompts when A/B-ing context.

### Data flow

```
worker start
  → ensure_worker_env / ensure_fleet_config
  → ensure_operator_env (write-if-missing defaults; prompts for sizing)
  → reload keys into os.environ from file
  → launch fleet using only env-backed values
  → job subprocess inherits AUTOANNOTATION_* from parent
  → autoannotation reads SECTION_CHUNKING from env
```

### Error handling

- Invalid int for slot ctx / max loaded / servers / parallel / slots: fail startup with a clear error naming the key (do not silently fall back to a constant).
- Invalid chunking flag: treat as default `true` **or** fail startup—prefer **fail startup** after materialize so operators notice typos (or: if value present but unparsable, rewrite is wrong; raise).

### Testing

- Unit: write-if-missing for slot ctx, keep-alive, max-loaded, chunking; second start does not rewrite user edits.
- Unit: tier refresh does not change keep-alive / max-loaded when keys exist in file.
- Unit: serve/bench path does not call tier keep-alive override (or equivalent integration assert on env after configure).
- Unit: `effective_ollama_context_length` uses env slot × parallel only.
- Unit: chunking `false` → expand is identity; `true` → still splits oversized sections.
- Update `worker.env.example` comments to match env-as-truth (remove “tier defaults overwrite keep-alive”).

## Success criteria

- No runtime use of keep-alive, slot ctx, max loaded, servers, parallel, max slots, or section chunking that was not first present in `worker.env` after ensure.
- Setting `OLLAMA_FLEET_KEEP_ALIVE=-1` in the file survives serve start on `vram_overflow`.
- Setting `OLLAMA_FLEET_SLOT_CTX=2048` with `PARALLEL=1` yields managed serve context 2048.
- `AUTOANNOTATION_SECTION_CHUNKING=false` yields one extractor unit per abstract/results/discussion block (no `#N` chunks).

## Implementation notes

- Prefer extending `shared.env_persist.resolve_value` / `save_env_file` patterns already used by bootstrap.
- Touch: `worker/fleet/setup.py`, `worker/serve.py`, `worker/bench.py`, `autoannotation/section_chunking.py` (or `autoannotation.py` wire-up), `worker.env.example`, `USAGE.md` / `worker/README.md`, tests under `tests/`.
