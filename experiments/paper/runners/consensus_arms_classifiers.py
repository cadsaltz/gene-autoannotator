"""Claim-support classifier adapters for consensus-arms Arm D (experiment only).

All heavy dependencies (``minicheck``, ``transformers``, ``torch``) are imported
lazily inside the backend loaders so importing this module is cheap and unit
tests never download models.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable, TypedDict


class ClassifierSkipped(Exception):
    """Raised when a classifier backend is unavailable or deliberately skipped."""


class ClassifierScore(TypedDict):
    claim_text: str
    score: float
    backend: str


def slice_excerpt(
    excerpt: str,
    max_chars: int = 6000,
    stride: int = 3000,
) -> list[str]:
    """Split ``excerpt`` into overlapping windows of at most ``max_chars``.

    Consecutive windows start ``stride`` characters apart (overlap is
    ``max_chars - stride``). The final window always reaches the end of the
    excerpt. Short/empty excerpts yield a single slice.
    """
    if max_chars <= 0 or stride <= 0:
        raise ValueError("max_chars and stride must be positive")
    if len(excerpt) <= max_chars:
        return [excerpt]
    slices: list[str] = []
    start = 0
    while True:
        end = start + max_chars
        slices.append(excerpt[start:end])
        if end >= len(excerpt):
            break
        start += stride
    return slices


@lru_cache(maxsize=None)
def _load_minicheck(model_name: str):
    try:
        from minicheck.minicheck import MiniCheck
    except ImportError as exc:
        raise ClassifierSkipped(f"minicheck package not installed: {exc}") from exc
    return MiniCheck(model_name=model_name, cache_dir="./ckpts")


def _score_minicheck(model_name: str, claim: str, passage: str) -> float:
    scorer = _load_minicheck(model_name)
    _labels, probs, _, _ = scorer.score(docs=[passage], claims=[claim])
    return float(probs[0])


def _score_minicheck_ft5(claim: str, passage: str) -> float:
    return _score_minicheck("flan-t5-large", claim, passage)


def _score_bespoke_minicheck_7b(claim: str, passage: str) -> float:
    try:
        import torch  # noqa: WPS433
    except ImportError as exc:
        raise ClassifierSkipped(f"torch not installed: {exc}") from exc
    if not torch.cuda.is_available():
        raise ClassifierSkipped("Bespoke-MiniCheck-7B requires a CUDA GPU")
    free_bytes, _total = torch.cuda.mem_get_info()
    # ~7B params in 4-bit needs roughly 6 GiB; skip otherwise.
    if free_bytes < 6 * 1024**3:
        raise ClassifierSkipped("insufficient free VRAM for Bespoke-MiniCheck-7B")
    return _score_minicheck("Bespoke-MiniCheck-7B", claim, passage)


@lru_cache(maxsize=None)
def _load_hhem():
    try:
        from transformers import AutoModelForSequenceClassification
    except ImportError as exc:
        raise ClassifierSkipped(f"transformers not installed: {exc}") from exc
    return AutoModelForSequenceClassification.from_pretrained(
        "vectara/hallucination_evaluation_model",
        trust_remote_code=True,
    )


def _score_hhem(claim: str, passage: str) -> float:
    model = _load_hhem()
    scores = model.predict([(passage, claim)])
    return float(scores[0])


def _score_nimble(claim: str, passage: str) -> float:
    raise ClassifierSkipped("quantization deferred")


# name -> fn(claim, passage) -> score for a single excerpt slice
_BACKENDS: dict[str, Callable[[str, str], float]] = {
    "minicheck_ft5": _score_minicheck_ft5,
    "hhem": _score_hhem,
    "bespoke_minicheck_7b": _score_bespoke_minicheck_7b,
    "nimble": _score_nimble,
}


def score_claim(backend: str, claim: str, excerpt: str) -> float:
    """Support score for ``claim`` against ``excerpt`` (max over excerpt slices)."""
    try:
        fn = _BACKENDS[backend]
    except KeyError as exc:
        raise ValueError(f"unknown classifier backend: {backend!r}") from exc
    return max(fn(claim, piece) for piece in slice_excerpt(excerpt))
