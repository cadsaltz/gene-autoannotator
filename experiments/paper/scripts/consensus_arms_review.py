"""Shared review helpers for the consensus-arms spreadsheet and compare scripts.

Adapted (not imported) from ``results/model_spread_15k/annotate_workbook.py``, which runs
on import.  Everything here is overlay-only: excerpt and model text are never changed,
only rich-text styling and separate flag text are produced.

Flag symbols (and no other symbols/emoji): ✔ real fact found, ◐ real but padded,
✖ false positive, ○ missed needle, ✓ correctly empty.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

BASE = dict(rFont="Calibri", sz=11)
F_PLAIN = InlineFont(**BASE)
F_NEEDLE = InlineFont(**BASE, b=True, u="double", color="006100")
F_REAL = InlineFont(**BASE, b=True, color="006100")
F_PADDED = InlineFont(**BASE, b=True, color="B35C00")
F_FP = InlineFont(**BASE, b=True, color="C00000")
OUTPUT_FONTS = {"REAL": F_REAL, "PADDED": F_PADDED, "FP": F_FP}

FP_KIND = {"unsupported": "hallucinated", "wrong_gene": "wrong gene", "contradicted": "contradicted"}
SEVERITY = {"REAL": 0, "PADDED": 1, "FP": 2}


def classify(label: str, gold_status: str) -> str:
    """Map a reviewer label to REAL / PADDED / FP."""
    if label == "correct":
        return "REAL"
    if label == "partial":
        return "PADDED" if gold_status != "absent" else "FP"
    return "FP"


def quote_segments(quote: str | None) -> list[str]:
    return [s.strip(" .") for s in re.split(r"\.\.\.|…", quote or "") if s.strip(" .")]


def flex_pattern(segment: str) -> str:
    return r"\s*".join(re.escape(tok) for tok in segment.split())


def styled_excerpt(text: str, quotes: list[str | None]) -> tuple[CellRichText | None, int]:
    """Rich text with needle quotes styled; ``str(result) == text`` always holds.

    Returns ``(None, found)`` when nothing in ``text`` matched (leave the cell plain).
    """
    level = [0] * len(text)
    found = 0
    for quote in quotes:
        for seg in quote_segments(quote):
            m = re.search(flex_pattern(seg), text)
            if m:
                found += 1
                for i in range(m.start(), m.end()):
                    level[i] = 1
    if not any(level):
        return None, found
    fonts = {0: F_PLAIN, 1: F_NEEDLE}
    runs, start = [], 0
    for i in range(1, len(text) + 1):
        if i == len(text) or level[i] != level[start]:
            runs.append(TextBlock(fonts[level[start]], text[start:i]))
            start = i
    return CellRichText(runs), found


def styled_output(text: str, field_class: dict[str, str]) -> CellRichText | None:
    """Colour each JSON field of a pretty-printed output cell by REAL / PADDED / FP."""
    spans = []
    for fld, cls in field_class.items():
        font = OUTPUT_FONTS.get(cls)
        if font is None:
            continue
        m = re.search(r'\n  "%s": ' % re.escape(fld), text)
        if not m:
            continue
        nxt = re.search(r'\n  "|\n}', text[m.end():])
        end = m.end() + nxt.start() if nxt else len(text)
        spans.append((m.start() + 1, end, font))
    if not spans:
        return None
    spans.sort(key=lambda s: s[:2])
    runs, pos = [], 0
    for s, e, font in spans:
        if s > pos:
            runs.append(TextBlock(F_PLAIN, text[pos:s]))
        runs.append(TextBlock(font, text[s:e]))
        pos = e
    if pos < len(text):
        runs.append(TextBlock(F_PLAIN, text[pos:]))
    return CellRichText(runs)


def short(v: Any, n: int = 160) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "..."


def needles_of(label_doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(f, d) for f, d in label_doc["fields"].items() if d["gold_status"] == "present"]


def needle_context(text: str, needles: list[tuple[str, dict[str, Any]]], note: str) -> CellRichText:
    """Column-G rich text: each needle shown inside its surrounding excerpt context."""
    bold = InlineFont(**BASE, b=True)
    small = InlineFont(rFont="Calibri", sz=9, i=True, color="595959")
    runs = [TextBlock(bold, f"{len(needles)} NEEDLE(S) IN THIS EXCERPT\n")]
    for fld, d in needles:
        runs.append(TextBlock(bold, f"\n- {fld}: "))
        runs.append(TextBlock(F_PLAIN, f"{short(d['gold_value'], 200)}\n"))
        for seg in quote_segments(d["gold_quote"]):
            m = re.search(flex_pattern(seg), text)
            if not m:
                continue
            lo, hi = max(0, m.start() - 160), min(len(text), m.end() + 160)
            runs.append(TextBlock(small, f"   at char {m.start():,} of {len(text):,}: "))
            runs.append(TextBlock(F_PLAIN, ("..." if lo else "") + text[lo:m.start()].replace("\n", " ")))
            runs.append(TextBlock(F_NEEDLE, text[m.start():m.end()].replace("\n", " ")))
            runs.append(TextBlock(F_PLAIN, text[m.end():hi].replace("\n", " ")
                                  + ("..." if hi < len(text) else "") + "\n"))
    runs.append(TextBlock(small, f"\nReviewer: {note}"))
    return CellRichText(runs)


Resolver = Callable[[str, Any, dict[str, Any]], "dict[str, Any] | None"]


def _evaluate(label_doc: dict[str, Any], output: Any, resolve: Resolver) -> dict[str, Any]:
    """Classify every field of ``output`` against ``label_doc``.

    ``resolve(field, value, field_doc)`` returns the reviewer label dict for that
    non-null value (or None when no label applies -> UNLABELED).
    """
    classes: dict[str, str] = {}
    notes: dict[str, str] = {}
    missed: list[str] = []
    quiet: list[str] = []
    kinds: dict[str, str] = {}
    out = output if isinstance(output, dict) else {}
    for fld, d in label_doc["fields"].items():
        v = out.get(fld)
        if v is None:
            (missed if d["gold_status"] == "present" else quiet).append(fld)
            continue
        lab = resolve(fld, v, d)
        if lab is None:
            classes[fld] = "UNLABELED"
            continue
        classes[fld] = classify(lab["label"], d["gold_status"])
        kinds[fld] = FP_KIND.get(lab["label"], "overreach")
        if lab.get("note"):
            notes[fld] = lab["note"]
    return {"classes": classes, "notes": notes, "missed": missed, "quiet": quiet, "kinds": kinds}


def evaluate_candidate(label_doc: dict[str, Any], model: str, output: Any) -> dict[str, Any]:
    """Evaluate one extractor's own output using that model's labels."""
    return _evaluate(label_doc, output, lambda f, v, d: d["labels"].get(model))


def evaluate_arm_output(
    label_doc: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    arm_output: Any,
) -> dict[str, Any]:
    """Evaluate an arm's decision output.

    Labels are per extractor model, so a non-null arm value inherits the label of the
    trio candidate(s) that proposed exactly that value (worst label wins).  A value no
    candidate proposed (e.g. a judge-merged rewrite) is UNLABELED, never guessed.
    """

    def resolve(fld: str, value: Any, d: dict[str, Any]) -> dict[str, Any] | None:
        best = None
        for model, cand in (candidates or {}).items():
            if not isinstance(cand, dict) or cand.get(fld) != value:
                continue
            lab = d["labels"].get(model)
            if lab is None:
                continue
            sev = SEVERITY[classify(lab["label"], d["gold_status"])]
            if best is None or sev > best[0]:
                best = (sev, lab)
        return best[1] if best else None

    return _evaluate(label_doc, arm_output, resolve)


def flag_text(res: dict[str, Any], has_needles: bool) -> str:
    classes = res["classes"]
    real = [f for f, c in classes.items() if c == "REAL"]
    padded = [f for f, c in classes.items() if c == "PADDED"]
    fps = [f for f, c in classes.items() if c == "FP"]
    unlabeled = [f for f, c in classes.items() if c == "UNLABELED"]
    lines = []
    if real:
        lines.append("✔ REAL FACT FOUND: " + ", ".join(real))
    if padded:
        lines.append("◐ REAL FACT, PADDED with unsupported extras: " + ", ".join(padded))
    if fps:
        lines.append("✖ FALSE POSITIVE: " + ", ".join(f"{f} ({res['kinds'][f]})" for f in fps))
    if res["missed"]:
        lines.append("○ MISSED needle: " + ", ".join(res["missed"]))
    if unlabeled:
        lines.append("UNLABELED value (no reviewer label matches): " + ", ".join(unlabeled))
    if not lines:
        lines.append("✓ correctly empty (no needles in this excerpt)" if not has_needles else "")
    notes = [f"  - {f}: {n}" for f, n in res["notes"].items() if classes.get(f) not in ("REAL", None)]
    return "\n".join(lines + notes)


def tally(res: dict[str, Any], label_doc: dict[str, Any]) -> dict[str, list[str]]:
    """Per-field buckets used by the scoreboard (needle fields vs no-needle fields)."""
    needle_fields = {f for f, _ in needles_of(label_doc)}
    buckets: dict[str, list[str]] = {
        "found_clean": [], "found_padded": [], "missed": list(res["missed"]),
        "fp": [], "unlabeled": [], "correctly_empty": list(res["quiet"]),
        "extra_supported": [], "unlabeled_needles": [],
    }
    for fld, cls in res["classes"].items():
        if cls in ("REAL", "PADDED") and fld not in needle_fields:
            buckets["extra_supported"].append(fld)  # supported value on a no-needle field
        elif cls == "REAL":
            buckets["found_clean"].append(fld)
        elif cls == "PADDED":
            buckets["found_padded"].append(fld)
        elif cls == "FP":
            buckets["fp"].append(fld)
        else:
            buckets["unlabeled"].append(fld)
            if fld in needle_fields:  # non-null value on a needle that needs judging
                buckets["unlabeled_needles"].append(fld)
    buckets["_needle_fields"] = sorted(needle_fields)
    return buckets
