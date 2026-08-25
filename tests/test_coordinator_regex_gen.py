import re

import pytest

from backend import regex_gen


def test_regex_from_examples_infers_clean_pattern():
    result = regex_gen.regex_from_examples(["Rv1000", "Rv2070c", "Rv3415A"])

    assert result["regex"] == r"^Rv\d{4}[Ac]?$"
    assert all(entry["ok"] for entry in result["matched"])
    assert [entry["value"] for entry in result["matched"]] == [
        "Rv1000",
        "Rv2070c",
        "Rv3415A",
    ]
    assert result["explanation"]


def test_regex_from_examples_strips_and_dedupes():
    result = regex_gen.regex_from_examples([" Rv1000 ", "Rv1000", "", "Rv2070c"])

    compiled = re.compile(result["regex"])
    assert compiled.fullmatch("Rv1000")
    assert compiled.fullmatch("Rv2070c")
    assert len(result["matched"]) == 2


def test_regex_from_examples_requires_examples():
    with pytest.raises(ValueError):
        regex_gen.regex_from_examples(["", "   "])


class _FakeBuilder:
    def __init__(self, pattern):
        self._pattern = pattern

    @classmethod
    def factory(cls, pattern):
        def from_test_cases(_cases):
            return cls(pattern)

        return type("_Builder", (), {"from_test_cases": staticmethod(from_test_cases)})

    def with_conversion_of_digits(self):
        return self

    def with_conversion_of_repetitions(self):
        return self

    def build(self):
        return self._pattern


def test_regex_from_examples_rejects_uncompilable_pattern(monkeypatch):
    monkeypatch.setattr(
        regex_gen, "RegExpBuilder", _FakeBuilder.factory("^Rv(\\d{4}$")
    )

    with pytest.raises(ValueError):
        regex_gen.regex_from_examples(["Rv1000"])


class _FakeOllama:
    def __init__(self, content=None, error=None):
        self._content = content
        self._error = error
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return {"message": {"content": self._content}}


def test_regex_from_description_returns_validated_regex(monkeypatch):
    fake = _FakeOllama(
        content='{"regex": "^Rv\\\\d{4}[Ac]?$", "explanation": "Rv plus four digits."}'
    )
    monkeypatch.setattr(regex_gen, "ollama", fake)

    result = regex_gen.regex_from_description("Rv then 4 digits then c, A, or nothing")

    assert result["regex"] == r"^Rv\d{4}[Ac]?$"
    assert result["explanation"] == "Rv plus four digits."
    assert result["matched"] == []
    assert fake.calls[0]["model"] == regex_gen.models.MODEL_REGEX


def test_regex_from_description_requires_text():
    with pytest.raises(ValueError):
        regex_gen.regex_from_description("   ")


def test_regex_from_description_raises_when_model_unavailable(monkeypatch):
    fake = _FakeOllama(error=ConnectionError("connection refused"))
    monkeypatch.setattr(regex_gen, "ollama", fake)

    with pytest.raises(regex_gen.RegexGenerationError):
        regex_gen.regex_from_description("anything")


def test_regex_from_description_rejects_invalid_regex(monkeypatch):
    fake = _FakeOllama(content='{"regex": "^Rv(\\\\d{4}", "explanation": "broken"}')
    monkeypatch.setattr(regex_gen, "ollama", fake)

    with pytest.raises(regex_gen.RegexGenerationError):
        regex_gen.regex_from_description("Rv then digits")


def test_regex_from_description_rejects_unparseable_response(monkeypatch):
    fake = _FakeOllama(content="not json at all")
    monkeypatch.setattr(regex_gen, "ollama", fake)

    with pytest.raises(regex_gen.RegexGenerationError):
        regex_gen.regex_from_description("Rv then digits")


def test_regex_from_description_rejects_non_string_regex(monkeypatch):
    fake = _FakeOllama(content='{"regex": 1234, "explanation": "not a string"}')
    monkeypatch.setattr(regex_gen, "ollama", fake)

    with pytest.raises(regex_gen.RegexGenerationError):
        regex_gen.regex_from_description("Rv then digits")
