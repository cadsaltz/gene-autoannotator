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
    warmed: list[str] = []
    for name in required:
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
