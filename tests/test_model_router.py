import threading
import time

import pytest

from worker.router import Backend, ModelNotFoundError, ModelRouter


def test_route_picks_least_loaded_backend():
    router = ModelRouter(
        [
            Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1),
            Backend(host="http://127.0.0.1:11435", models={"gemma3:1b"}, parallel=1),
        ]
    )
    b1 = router.acquire("gemma3:1b")
    b2 = router.acquire("gemma3:1b")
    assert b1.host != b2.host
    router.release(b1, "gemma3:1b")
    b3 = router.acquire("gemma3:1b")
    assert b3.host == b1.host


def test_acquire_blocks_when_server_gate_saturated():
    router = ModelRouter(
        [Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1)]
    )
    held = router.acquire("gemma3:1b")
    acquired = threading.Event()
    result: list[Backend] = []

    def waiter() -> None:
        result.append(router.acquire("gemma3:1b"))
        acquired.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.05)
    assert not acquired.is_set()

    router.release(held, "gemma3:1b")
    thread.join(timeout=1.0)
    assert acquired.is_set()
    assert len(result) == 1
    assert result[0].host == held.host


def test_different_models_share_server_gate():
    router = ModelRouter(
        [
            Backend(
                host="http://127.0.0.1:11434",
                models={"gemma3:1b", "qwen3:0.6b"},
                parallel=1,
            )
        ]
    )
    gemma = router.acquire("gemma3:1b")
    acquired = threading.Event()
    qwen_result: list[Backend] = []

    def waiter() -> None:
        qwen_result.append(router.acquire("qwen3:0.6b"))
        acquired.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.05)
    assert not acquired.is_set()

    router.release(gemma, "gemma3:1b")
    thread.join(timeout=1.0)
    assert acquired.is_set()
    assert len(qwen_result) == 1
    router.release(qwen_result[0], "qwen3:0.6b")


def test_parallel_two_allows_two_models_concurrently():
    router = ModelRouter(
        [
            Backend(
                host="http://127.0.0.1:11434",
                models={"gemma3:1b", "qwen3:0.6b"},
                parallel=2,
            )
        ]
    )
    gemma = router.acquire("gemma3:1b")
    qwen = router.acquire("qwen3:0.6b")
    assert gemma.host == qwen.host

    blocked = threading.Event()

    def waiter() -> None:
        router.acquire("gemma3:1b")
        blocked.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.05)
    assert not blocked.is_set()

    router.release(gemma, "gemma3:1b")
    thread.join(timeout=1.0)
    assert blocked.is_set()
    router.release(qwen, "qwen3:0.6b")


def test_unknown_model_raises():
    router = ModelRouter(
        [Backend(host="http://127.0.0.1:11434", models={"gemma3:1b"}, parallel=1)]
    )
    with pytest.raises(ModelNotFoundError, match="unknown-model"):
        router.acquire("unknown-model")
