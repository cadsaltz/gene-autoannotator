import logging

from autoannotation import models

log = logging.getLogger(__name__)


def required_models():
    # Derived from the same config the annotator reads, so the set never drifts.
    names = set(models.MODEL_SUMMARY) | {models.MODEL_CONSENSUS, models.MODEL_AGGREGATION}
    return {name for name in names if name}


def _model_entries(list_result):
    if isinstance(list_result, dict):
        return list_result.get("models", [])
    models = getattr(list_result, "models", None)
    if models is not None:
        return models
    return list_result


def _installed_names(list_result):
    names = set()
    for entry in _model_entries(list_result):
        if isinstance(entry, dict):
            name = entry.get("model") or entry.get("name")
        else:
            name = getattr(entry, "model", None) or getattr(entry, "name", None)
        if name:
            names.add(name)
    return names


def ensure_models(*, client=None, required=None):
    if client is None:
        import ollama

        client = ollama
    required = sorted(required if required is not None else required_models())
    installed = _installed_names(client.list())
    missing = [name for name in required if name not in installed]
    for name in missing:
        log.info("Pulling missing Ollama model %s", name)
        print(f"Pulling Ollama model {name}...", flush=True)
        client.pull(name)
        print(f"Pulled Ollama model {name}", flush=True)
    return missing


def _ps_model_names(ps_result) -> set[str]:
    if isinstance(ps_result, dict):
        entries = ps_result.get("models", [])
    else:
        entries = getattr(ps_result, "models", []) or []
    names: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("model")
        else:
            name = getattr(entry, "name", None) or getattr(entry, "model", None)
        if name:
            names.add(str(name))
            if ":" in str(name):
                names.add(str(name).split(":", 1)[0])
    return names


def models_loaded(*, client=None, host: str | None = None, required=None) -> list[str]:
    """Return required model names not currently resident according to ``ollama ps``."""
    if client is None:
        import ollama

        client = ollama.Client(host=host) if host else ollama
    required = sorted(required if required is not None else required_models())
    loaded = _ps_model_names(client.ps())
    missing: list[str] = []
    for name in required:
        base = name.split(":", 1)[0]
        if name not in loaded and base not in loaded:
            missing.append(name)
    return missing


def _warm_order(names: list[str], *, host: str | None = None) -> list[str]:
    """Warm smaller models first; load largest (usually aggregation) last."""
    if not host:
        return sorted(names)
    try:
        from worker.fleet.models import manifest_model_sizes

        sizes = manifest_model_sizes(host=host)
    except Exception:
        sizes = {}
    return sorted(names, key=lambda n: sizes.get(n, 0))


def should_prewarm(*, model_sizes: dict[str, int], budget_bytes: int) -> bool:
    """Return True only when the full required stack fits in the cache budget."""
    if budget_bytes <= 0 or not model_sizes:
        return False
    if any(size <= 0 for size in model_sizes.values()):
        return False
    return sum(model_sizes.values()) <= budget_bytes


def warm_all_models(
    *,
    client=None,
    host: str | None = None,
    required=None,
    keep_alive: int | str = -1,
) -> list[str]:
    """Load each required model and pin it in memory (default keep_alive=-1).

    Issues a minimal chat per model so Ollama loads weights before batch work.
    With keep_alive=-1, models stay loaded until Ollama restarts or they are
    explicitly unloaded.
    """
    if client is None:
        import ollama

        client = ollama.Client(host=host) if host else ollama
    from worker.ollama_keep_alive import parse_ollama_keep_alive

    parsed_keep_alive = parse_ollama_keep_alive(keep_alive)
    if parsed_keep_alive is None:
        parsed_keep_alive = -1

    required = sorted(required if required is not None else required_models())
    warm_order = _warm_order(required, host=host)
    warmed: list[str] = []
    for name in warm_order:
        log.info("Warming Ollama model %s (keep_alive=%s)", name, parsed_keep_alive)
        print(
            f"Warming Ollama model {name} (keep_alive={parsed_keep_alive})...",
            flush=True,
        )
        client.chat(
            model=name,
            messages=[{"role": "user", "content": "ping"}],
            keep_alive=parsed_keep_alive,
        )
        warmed.append(name)
        print(f"Warmed Ollama model {name}", flush=True)
    return warmed
