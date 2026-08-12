from worker.ollama_bootstrap import should_prewarm


def test_should_prewarm_only_when_full_stack_fits():
    sizes = {"a": 3, "b": 3, "c": 3}
    assert should_prewarm(model_sizes=sizes, budget_bytes=10) is True
    assert should_prewarm(model_sizes=sizes, budget_bytes=8) is False


def test_should_prewarm_rejects_empty_or_invalid():
    assert should_prewarm(model_sizes={}, budget_bytes=10) is False
    assert should_prewarm(model_sizes={"a": 1}, budget_bytes=0) is False
    assert should_prewarm(model_sizes={"a": 0}, budget_bytes=10) is False
