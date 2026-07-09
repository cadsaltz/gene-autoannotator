import importlib

from worker.fleet import models


def _reload_model_config():
    from autoannotation import models as ann_models
    from worker import ollama_bootstrap

    importlib.reload(ann_models)
    importlib.reload(ollama_bootstrap)
    importlib.reload(models)


def test_required_models_for_nano(monkeypatch):
    monkeypatch.setenv("AUTOANNOTATION_MODEL_MODE", "nano")
    _reload_model_config()
    names = models.required_model_names()
    assert "gemma3:1b" in names
    assert len(names) == 4


def test_estimate_w_all_sums_manifest_sizes(monkeypatch):
    monkeypatch.setattr(
        models,
        "_model_size_bytes",
        lambda name: {"a": 1_000_000_000, "b": 500_000_000}[name],
    )
    assert models.estimate_w_all_bytes(["a", "b"]) == 1_500_000_000
