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


def test_estimate_w_peak_uses_largest_model(monkeypatch):
    monkeypatch.setattr(
        models,
        "_model_size_bytes",
        lambda name: {"a": 1_000_000_000, "b": 500_000_000}[name],
    )
    assert models.estimate_w_peak_bytes(["a", "b"]) == 1_000_000_000


def test_parse_size_token():
    assert models._parse_size_token("815 MB") == 815 * 1024**2
    assert models._parse_size_token("7.3 GB") == int(7.3 * 1024**3)


def test_size_from_ollama_list_parses_name_and_size():
    listing = (
        "NAME                    ID              SIZE      MODIFIED\n"
        "gemma3:1b               abc123          815 MB    2 days ago\n"
    )
    size = models._size_from_ollama_list_text("gemma3:1b", listing)
    assert size == 815 * 1024**2


def test_model_size_bytes_falls_back_without_ollama(monkeypatch):
    monkeypatch.setattr(models, "_size_from_ollama_list", lambda _name: None)
    monkeypatch.setattr(models, "_size_from_show_json", lambda _name: None)
    monkeypatch.setattr(models, "_size_from_show_api", lambda _name: None)
    monkeypatch.setenv("AUTOANNOTATION_MODEL_MODE", "nano")
    size = models._model_size_bytes("gemma3:1b")
    assert size == models._MODE_W_ALL_ESTIMATE_BYTES["nano"] // 1


def test_estimate_w_all_uses_mode_fallback_when_probes_empty(monkeypatch):
    monkeypatch.setattr(models, "_model_size_bytes", lambda _name: 0)
    monkeypatch.setenv("AUTOANNOTATION_MODEL_MODE", "nano")
    # sum of zeros triggers mode-level fallback
    assert models.estimate_w_all_bytes(["a", "b"]) == models._MODE_W_ALL_ESTIMATE_BYTES["nano"]
