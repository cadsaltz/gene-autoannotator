from worker import ollama_bootstrap


class FakeOllama:
    def __init__(self, installed):
        self._installed = list(installed)
        self.pulled = []

    def list(self):
        return {"models": [{"model": name} for name in self._installed]}

    def pull(self, model):
        self.pulled.append(model)
        self._installed.append(model)


def test_required_models_includes_summary_consensus_aggregation():
    from autoannotation import models

    required = ollama_bootstrap.required_models()
    assert set(models.MODEL_SUMMARY).issubset(required)
    assert models.MODEL_CONSENSUS in required
    assert models.MODEL_AGGREGATION in required


def test_ensure_models_pulls_only_missing():
    from autoannotation import models

    required = sorted(ollama_bootstrap.required_models())
    client = FakeOllama(installed=[required[0]])
    ollama_bootstrap.ensure_models(client=client, required=required)
    assert client.pulled == required[1:]
    assert required[0] not in client.pulled
