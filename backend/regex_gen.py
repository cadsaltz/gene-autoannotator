import json
import re

import ollama
from grex import RegExpBuilder

from autoannotation import models


class RegexGenerationError(RuntimeError):
    """Raised when a regex cannot be generated from a natural-language description."""


REGEX_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "regex": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["regex", "explanation"],
}


def _clean_examples(examples):
    cleaned = []
    seen = set()
    for raw in examples or []:
        value = (raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned


def _examples_explanation(count):
    return (
        f"Inferred from {count} example value(s). The pattern is anchored, so a "
        "locus must match it from start to end. Every example you supplied "
        "matches this pattern."
    )


def regex_from_examples(examples):
    cleaned = _clean_examples(examples)
    if not cleaned:
        raise ValueError("at least one example locus is required")
    try:
        pattern = (
            RegExpBuilder.from_test_cases(cleaned)
            .with_conversion_of_digits()
            .with_conversion_of_repetitions()
            .build()
        )
    except Exception as exc:  # noqa: BLE001 - surface degenerate input as a 422.
        raise ValueError(f"could not infer a regex from these examples: {exc}") from exc
    # grex emits patterns in Rust's regex dialect, which is not guaranteed to be
    # a strict subset of Python's re. Treat an uncompilable pattern as bad input
    # rather than letting it crash the request.
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(
            f"the inferred pattern could not be compiled as a regex: {exc}"
        ) from exc
    matched = [{"value": value, "ok": bool(compiled.fullmatch(value))} for value in cleaned]
    return {
        "regex": pattern,
        "explanation": _examples_explanation(len(cleaned)),
        "matched": matched,
    }


# regex-from-description prompt
description_prompt_tmpl = '''
You convert a description of a gene locus identifier format into a single
Python-compatible regular expression.

Rules:
- Anchor the pattern with ^ and $.
- The 'regex' field must contain only the regex: no code fences, no quotes, no commentary.
- The 'explanation' field is a short plain-English description of what the regex matches.

Description: {0}
'''


def _build_description_prompt(description):
    return description_prompt_tmpl.format(description)


def regex_from_description(description):
    text = (description or "").strip()
    if not text:
        raise ValueError("description is required")
    prompt = _build_description_prompt(text)
    try:
        response = ollama.chat(
            model=models.MODEL_REGEX,
            messages=[{"role": "user", "content": prompt}],
            format=REGEX_JSON_SCHEMA,
            options={"temperature": 0},
        )
        content = response["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - any Ollama failure is a generation failure.
        raise RegexGenerationError(f"regex model is unavailable: {exc}") from exc
    try:
        data = json.loads(content)
        regex = (data["regex"] or "").strip()
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise RegexGenerationError("model returned an unparseable response") from exc
    if not regex:
        raise RegexGenerationError("model did not return a regex")
    try:
        re.compile(regex)
    except re.error as exc:
        raise RegexGenerationError(f"model returned an invalid regex: {exc}") from exc
    explanation = (data.get("explanation") or "").strip()
    return {"regex": regex, "explanation": explanation, "matched": []}
