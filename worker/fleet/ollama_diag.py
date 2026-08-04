"""Summarize noisy Ollama / llama.cpp serve logs into actionable diagnostics."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Literal

Phase = Literal["loading", "idle", "inferencing", "dead", "unknown"]

_RE_TRUNCATE = re.compile(
    r"truncating input prompt.*?limit=(?P<limit>\d+).*?prompt=(?P<prompt>\d+)",
    re.IGNORECASE,
)
_RE_TRUNCATED_FLAG = re.compile(r"truncated\s*=\s*1\b")
_RE_LAYERS = re.compile(
    r"offloaded\s+(?P<gpu>\d+)\s*/\s*(?P<total>\d+)\s+layers\s+to\s+GPU",
    re.IGNORECASE,
)
_RE_RUNNERS = re.compile(r"loaded runners.*?count=(?P<count>\d+)", re.IGNORECASE)
_RE_GIN_CHAT = re.compile(
    r"\[GIN\].*?\|\s*(?P<status>\d{3})\s*\|\s*(?P<dur>[^\|]+)\|\s*[^\|]*\|\s*"
    r"(?P<method>GET|POST|PUT|DELETE|PATCH)\s+\"(?P<path>/api/chat[^\"]*)\"",
    re.IGNORECASE,
)
_RE_DURATION = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>µs|us|ms|s)",
    re.IGNORECASE,
)
_RE_FIT_FAIL = re.compile(r"cannot meet free memory", re.IGNORECASE)
_RE_FIT_OK = re.compile(r"successfully fit params", re.IGNORECASE)
_RE_LIMITED_VRAM = re.compile(r"limited-vram|disabling multimodal projector offload", re.IGNORECASE)
_RE_CUDA_OOM = re.compile(
    r"CUDA\s*(?:error|out of memory)|out of memory|ggml_gallocr_reserve|failed to allocate",
    re.IGNORECASE,
)
_RE_LOAD_FAIL = re.compile(r"failed to load|error loading model|load_model:.*fail", re.IGNORECASE)
_RE_EXIT = re.compile(r"\*\*\*.*exited unexpectedly|\*\*\*.*exited\b", re.IGNORECASE)
_RE_LOADING = re.compile(
    r"llm server loading model|loading model via llama-server|srv\s+llama_server:\s+loading model|"
    r"load_tensors:\s+loading model tensors",
    re.IGNORECASE,
)
_RE_IDLE = re.compile(r"all slots are idle|srv\s+llama_server:\s+model loaded", re.IGNORECASE)
_RE_BUSY = re.compile(
    r"processing task|prompt processing|prompt eval time|launch_slot_",
    re.IGNORECASE,
)


@dataclass
class OllamaAlert:
    code: str
    message: str


@dataclass
class OllamaLastChat:
    status: int
    duration_s: float


@dataclass
class OllamaDiagSummary:
    phase: Phase = "unknown"
    runners: int | None = None
    layers_on_gpu: int | None = None
    layers_total: int | None = None
    last_chat: OllamaLastChat | None = None
    alerts: list[OllamaAlert] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def _set_alert(alerts: dict[str, str], code: str, message: str) -> None:
    alerts[code] = message


def _clear_alert(alerts: dict[str, str], code: str) -> None:
    alerts.pop(code, None)


def _parse_duration_seconds(raw: str) -> float | None:
    text = raw.strip()
    match = _RE_DURATION.search(text)
    if not match:
        return None
    value = float(match.group("val"))
    unit = match.group("unit").lower()
    if unit in {"µs", "us"}:
        return value / 1_000_000.0
    if unit == "ms":
        return value / 1000.0
    return value


def summarize_ollama_lines(lines: Iterable[str]) -> OllamaDiagSummary:
    """Walk serve log lines in order and produce a sticky diagnostic summary."""
    phase: Phase = "unknown"
    runners: int | None = None
    layers_on_gpu: int | None = None
    layers_total: int | None = None
    last_chat: OllamaLastChat | None = None
    alerts: dict[str, str] = {}

    for raw in lines:
        line = raw.rstrip("\n\r")
        if not line:
            continue

        if _RE_EXIT.search(line):
            phase = "dead"
            _set_alert(alerts, "exited", line.strip(" *"))
            continue

        trunc = _RE_TRUNCATE.search(line)
        if trunc:
            limit = trunc.group("limit")
            prompt = trunc.group("prompt")
            _set_alert(
                alerts,
                "prompt_truncated",
                (
                    f"truncating prompt {prompt}→{limit} (slot ctx); "
                    "raise ctx or set parallel=1"
                ),
            )

        if _RE_TRUNCATED_FLAG.search(line) and "prompt_truncated" not in alerts:
            _set_alert(
                alerts,
                "prompt_truncated",
                "request finished with truncated=1 (prompt likely exceeded slot ctx)",
            )

        layers = _RE_LAYERS.search(line)
        if layers:
            layers_on_gpu = int(layers.group("gpu"))
            layers_total = int(layers.group("total"))

        runners_m = _RE_RUNNERS.search(line)
        if runners_m:
            runners = int(runners_m.group("count"))

        if _RE_LIMITED_VRAM.search(line):
            _set_alert(
                alerts,
                "limited_vram",
                "limited VRAM (e.g. multimodal projector kept on CPU)",
            )

        if _RE_FIT_FAIL.search(line):
            _set_alert(
                alerts,
                "vram_fit_failed",
                "cannot meet free GPU memory target while fitting model",
            )

        if _RE_FIT_OK.search(line):
            _clear_alert(alerts, "vram_fit_failed")

        if _RE_CUDA_OOM.search(line):
            _set_alert(alerts, "oom", "GPU/host out of memory while loading or running")

        if _RE_LOAD_FAIL.search(line):
            _set_alert(alerts, "load_failed", "model load failed (see ollama-server log)")

        gin = _RE_GIN_CHAT.search(line)
        if gin:
            status = int(gin.group("status"))
            duration_s = _parse_duration_seconds(gin.group("dur")) or 0.0
            last_chat = OllamaLastChat(status=status, duration_s=duration_s)
            if status >= 500:
                _set_alert(
                    alerts,
                    "chat_http_error",
                    f"/api/chat returned HTTP {status}",
                )
            elif status >= 400:
                _set_alert(
                    alerts,
                    "chat_http_error",
                    f"/api/chat returned HTTP {status}",
                )
            else:
                _clear_alert(alerts, "chat_http_error")
            if phase != "dead":
                phase = "idle"
            continue

        if phase != "dead":
            if _RE_LOADING.search(line):
                phase = "loading"
            elif _RE_BUSY.search(line):
                phase = "inferencing"
            elif _RE_IDLE.search(line):
                phase = "idle"

    return OllamaDiagSummary(
        phase=phase,
        runners=runners,
        layers_on_gpu=layers_on_gpu,
        layers_total=layers_total,
        last_chat=last_chat,
        alerts=[OllamaAlert(code=code, message=msg) for code, msg in alerts.items()],
    )


def format_summary_lines(summary: OllamaDiagSummary | dict[str, Any]) -> list[str]:
    """Dashboard-oriented lines under the OLLAMA header (no header itself)."""
    if isinstance(summary, dict):
        phase = summary.get("phase") or "unknown"
        runners = summary.get("runners")
        layers_on_gpu = summary.get("layers_on_gpu")
        layers_total = summary.get("layers_total")
        last_chat = summary.get("last_chat")
        alerts_raw = summary.get("alerts") or []
    else:
        phase = summary.phase
        runners = summary.runners
        layers_on_gpu = summary.layers_on_gpu
        layers_total = summary.layers_total
        last_chat = (
            {"status": summary.last_chat.status, "duration_s": summary.last_chat.duration_s}
            if summary.last_chat
            else None
        )
        alerts_raw = [{"code": a.code, "message": a.message} for a in summary.alerts]

    parts: list[str] = [f"phase: {phase}"]
    if runners is not None:
        parts.append(f"runners={runners}")
    if layers_on_gpu is not None and layers_total is not None:
        parts.append(f"layers {layers_on_gpu}/{layers_total} GPU")
    out = [f"  {' | '.join(parts)}"]

    if isinstance(last_chat, dict) and last_chat.get("status") is not None:
        duration = last_chat.get("duration_s")
        if isinstance(duration, (int, float)):
            if duration >= 10:
                dur_s = f"{duration:.1f}s"
            elif duration >= 1:
                dur_s = f"{duration:.2f}s"
            else:
                dur_s = f"{duration * 1000:.0f}ms"
        else:
            dur_s = "?"
        out.append(f"  last chat: {last_chat['status']} in {dur_s}")

    for alert in alerts_raw:
        if isinstance(alert, dict):
            message = alert.get("message") or alert.get("code") or "alert"
        else:
            message = str(alert)
        out.append(f"  ! {message}")
    return out
