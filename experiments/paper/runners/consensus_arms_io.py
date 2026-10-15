from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

MODEL_LETTER = {
    "gemma4:12b": "A",
    "qwen3.5:9b": "B",
    "mistral-nemo:12b": "C",
    "dolphin3:8b": "D",
    "ministral-3:14b": "E",
    "phi4:14b": "F",
    "granite4.2:8b": "G",
    "llama3.1:8b": "H",
    "rnj-1:8b": "I",
}

def packet_stem(trial_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", trial_id)

def load_biology_trials(records_path: Path) -> list[dict[str, Any]]:
    out = []
    with Path(records_path).open() as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "trial_observable" and row.get("trial_pool") == "biology":
                out.append(row)
    return out

def extractor_outputs_by_model(trial: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_model: dict[str, dict[str, Any]] = {}
    for cond, metrics in (trial.get("condition_metrics") or {}).items():
        if not str(cond).startswith("extractor_"):
            continue
        model = metrics["model"]
        by_model[model] = trial["outputs"][cond]
    return by_model

def load_labels(labels_dir: Path) -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for path in Path(labels_dir).glob("t*.json"):
        labels[path.stem] = json.loads(path.read_text())
    return labels
