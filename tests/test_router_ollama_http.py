from unittest.mock import MagicMock, patch

import httpx
import pytest

from worker.router.ollama_http import chat


def test_chat_posts_to_ollama_api():
    response = MagicMock()
    response.json.return_value = {
        "model": "gemma3:1b",
        "message": {"role": "assistant", "content": "{}"},
        "done": True,
    }
    response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = response

    with patch("worker.router.ollama_http.httpx.Client", return_value=mock_client):
        result = chat(
            "http://127.0.0.1:11434",
            model="gemma3:1b",
            messages=[{"role": "user", "content": "hi"}],
            timeout_sec=30.0,
        )

    assert result["message"]["content"] == "{}"
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://127.0.0.1:11434/api/chat"
    body = call_args[1]["json"]
    assert body["stream"] is False
    assert body["model"] == "gemma3:1b"


def test_chat_passes_keep_alive_and_format():
    response = MagicMock()
    response.json.return_value = {"done": True}
    response.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = response

    with patch("worker.router.ollama_http.httpx.Client", return_value=mock_client):
        chat(
            "http://127.0.0.1:11434",
            model="gemma3:1b",
            messages=[{"role": "user", "content": "hi"}],
            format={"type": "object"},
            keep_alive=-1,
            timeout_sec=10.0,
        )

    body = mock_client.post.call_args[1]["json"]
    assert body["keep_alive"] == -1
    assert body["format"] == {"type": "object"}


def test_chat_raises_on_timeout():
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
    )

    with patch("worker.router.ollama_http.httpx.Client", return_value=mock_client):
        with pytest.raises(httpx.ReadTimeout):
            chat(
                "http://127.0.0.1:11434",
                model="gemma3:1b",
                messages=[{"role": "user", "content": "hi"}],
                timeout_sec=1.0,
            )
