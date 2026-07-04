from autoannotation import http_


def test_ncbi_api_key_param_empty_when_unset(monkeypatch):
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.delenv("ENTREZ_API_KEY", raising=False)
    assert http_.ncbi_api_key_param() == ""


def test_ncbi_api_key_param_prefers_ncbi_api_key(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "abc123")
    monkeypatch.delenv("ENTREZ_API_KEY", raising=False)
    assert http_.ncbi_api_key_param() == "&api_key=abc123"


def test_ncbi_api_key_param_falls_back_to_entrez_api_key(monkeypatch):
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    monkeypatch.setenv("ENTREZ_API_KEY", "xyz789")
    assert http_.ncbi_api_key_param() == "&api_key=xyz789"
