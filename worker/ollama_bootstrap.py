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
        client.pull(name)
    return missing
