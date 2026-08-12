from worker.router import ollama_http


def test_unload_model_posts_keep_alive_zero(monkeypatch):
    calls = []

    def fake_generate(host, *, model, prompt="", keep_alive=None, timeout_sec=None):
        calls.append(
            {
                "host": host,
                "model": model,
                "prompt": prompt,
                "keep_alive": keep_alive,
                "timeout_sec": timeout_sec,
            }
        )
        return {"done": True, "done_reason": "unload"}

    monkeypatch.setattr(ollama_http, "generate", fake_generate)
    out = ollama_http.unload_model("http://127.0.0.1:11434", "gemma3:12b")
    assert out["done_reason"] == "unload"
    assert calls == [
        {
            "host": "http://127.0.0.1:11434",
            "model": "gemma3:12b",
            "prompt": "",
            "keep_alive": 0,
            "timeout_sec": 60.0,
        }
    ]
