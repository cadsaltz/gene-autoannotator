import sys

import pytest

from experiments.paper.runners import consensus_arms_classifiers as cls
from experiments.paper.runners.consensus_arms_classifiers import (
    ClassifierSkipped,
    score_claim,
    slice_excerpt,
)


def test_slice_excerpt_short_returns_single_slice():
    assert slice_excerpt("abc", max_chars=10, stride=5) == ["abc"]


def test_slice_excerpt_empty_returns_single_empty_slice():
    assert slice_excerpt("", max_chars=10, stride=5) == [""]


def test_slice_excerpt_overlaps_and_covers_tail():
    text = "".join(chr(ord("a") + i % 26) for i in range(25))
    slices = slice_excerpt(text, max_chars=10, stride=5)
    assert slices[0] == text[0:10]
    assert slices[1] == text[5:15]
    # consecutive slices overlap by max_chars - stride characters
    assert slices[0][5:] == slices[1][:5]
    assert all(len(s) <= 10 for s in slices)
    # last slice reaches the end of the excerpt
    assert slices[-1].endswith(text[-1])
    # no slice is fully contained in the previous one (no redundant tail)
    assert len(slices) == 4


def test_slice_excerpt_defaults():
    text = "x" * 9000
    slices = slice_excerpt(text)
    assert len(slices) == 2
    assert slices[0] == text[:6000]
    assert slices[1] == text[3000:9000]


def test_slice_excerpt_rejects_bad_stride():
    with pytest.raises(ValueError):
        slice_excerpt("abc", max_chars=10, stride=0)


def test_slice_excerpt_rejects_stride_gt_max_chars():
    with pytest.raises(ValueError):
        slice_excerpt("abc", max_chars=10, stride=11)


def test_bespoke_skipped_when_vram_below_full_precision(monkeypatch):
    class _FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def mem_get_info():
            return (2 * 1024**3, 8 * 1024**3)

    class _FakeTorch:
        cuda = _FakeCuda

    monkeypatch.setitem(sys.modules, "torch", _FakeTorch())
    with pytest.raises(ClassifierSkipped, match="4-bit"):
        cls._score_bespoke_minicheck_7b("claim", "passage")


def test_nimble_raises_skipped():
    with pytest.raises(ClassifierSkipped) as exc:
        score_claim("nimble", "claim", "excerpt")
    assert "quantization deferred" in str(exc.value)


def test_unknown_backend_raises_value_error():
    with pytest.raises(ValueError):
        score_claim("nope", "claim", "excerpt")


def test_score_claim_takes_max_over_slices(monkeypatch):
    seen = []

    def fake_backend(claim, passage):
        seen.append(passage)
        return 0.9 if passage.startswith("B") else 0.1

    monkeypatch.setitem(cls._BACKENDS, "hhem", fake_backend)
    excerpt = "A" * 6000 + "B" * 6000
    score = score_claim("hhem", "claim", excerpt)
    assert score == pytest.approx(0.9)
    assert len(seen) >= 2


def test_score_claim_dispatches_each_backend(monkeypatch):
    for name in ("minicheck_ft5", "hhem", "bespoke_minicheck_7b"):
        monkeypatch.setitem(cls._BACKENDS, name, lambda c, p, n=name: 0.5)
        assert score_claim(name, "c", "short excerpt") == 0.5


def test_backends_import_lazily():
    import subprocess

    code = (
        "import sys; "
        "import experiments.paper.runners.consensus_arms_classifiers; "
        "assert 'minicheck' not in sys.modules; "
        "assert 'transformers' not in sys.modules; "
        "assert 'torch' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
