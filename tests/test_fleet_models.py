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
        lambda name, **_kwargs: {"a": 1_000_000_000, "b": 500_000_000}[name],
    )
    assert models.estimate_w_all_bytes(["a", "b"]) == 1_500_000_000


def test_estimate_w_peak_uses_largest_model(monkeypatch):
    monkeypatch.setattr(
        models,
        "_model_size_bytes",
        lambda name, **_kwargs: {"a": 1_000_000_000, "b": 500_000_000}[name],
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
    monkeypatch.setattr(models, "_probe_model_size_bytes", lambda _name, host=None: None)
    monkeypatch.setattr(models, "required_model_names", lambda: ["a", "b", "c", "d"])
    monkeypatch.setenv("AUTOANNOTATION_MODEL_MODE", "nano")
    size = models._model_size_bytes("gemma3:1b")
    assert size == models._MODE_W_ALL_ESTIMATE_BYTES["nano"] // 4


def test_size_from_show_text_parses_size_field(monkeypatch):
    def fake_run(cmd, **kwargs):
        class Result:
            returncode = 0
            stdout = "  size\t815 MB\n  family\tgemma\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(models.subprocess, "run", fake_run)
    assert models._size_from_show_text("gemma3:1b") == 815 * 1024**2


def test_resolve_footprints_uses_manifest_when_complete(monkeypatch):
    monkeypatch.setattr(
        models,
        "manifest_model_sizes",
        lambda host: {
            "a": 1_000_000_000,
            "b": 500_000_000,
        },
    )
    monkeypatch.setattr(models, "required_model_names", lambda: ["a", "b"])
    monkeypatch.setattr(models, "measure_w_peak_runtime", lambda host: 900_000_000)
    w_all, w_peak, source = models.resolve_footprints(
        host="http://127.0.0.1:11434",
        measure_runtime_peak=True,
    )
    assert source == "runtime"
    assert w_all == 1_500_000_000
    assert w_peak == 900_000_000


def test_resolve_footprints_falls_back_to_estimate_without_host(monkeypatch):
    monkeypatch.setattr(models, "estimate_w_all_bytes", lambda: 2_000_000_000)
    monkeypatch.setattr(models, "estimate_w_peak_bytes", lambda: 1_000_000_000)
    w_all, w_peak, source = models.resolve_footprints(host=None)
    assert source == "estimate"
    assert w_all == 2_000_000_000
    assert w_peak == 1_000_000_000


def test_estimate_w_all_uses_mode_fallback_when_probes_empty(monkeypatch):
    monkeypatch.setattr(models, "_model_size_bytes", lambda _name, **_kwargs: 0)
    monkeypatch.setenv("AUTOANNOTATION_MODEL_MODE", "nano")
    # sum of zeros triggers mode-level fallback
    assert models.estimate_w_all_bytes(["a", "b"]) == models._MODE_W_ALL_ESTIMATE_BYTES["nano"]
