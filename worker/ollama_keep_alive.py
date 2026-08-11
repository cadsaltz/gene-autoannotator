from __future__ import annotations

import os

_FOREVER_ALIASES = frozenset(
    {"-1", "forever", "infinite", "inf", "infinity", "never", "permanent"}
)
_IMMEDIATE_UNLOAD_ALIASES = frozenset({"0", "false", "no", "unload", "immediate"})


def resolve_job_keep_alive(
    *,
    cli_value: str | None = None,
    fleet_keep_alive: str | None = None,
) -> str:
    """Resolve keep_alive for warm + LLM calls.

    Priority (same ground truth as other fleet knobs unless CLI overrides):
    1. Explicit ``--keep-alive`` CLI value
    2. ``AUTOANNOTATION_OLLAMA_KEEP_ALIVE`` (often copied from fleet apply)
    3. ``fleet_keep_alive`` / ``OLLAMA_FLEET_KEEP_ALIVE``
    4. ``-1`` (never unload)
    """
    if cli_value is not None and str(cli_value).strip() != "":
        return str(cli_value).strip()
    env_annotation = (os.getenv("AUTOANNOTATION_OLLAMA_KEEP_ALIVE") or "").strip()
    if env_annotation:
        return env_annotation
    if fleet_keep_alive is not None and str(fleet_keep_alive).strip() != "":
        return str(fleet_keep_alive).strip()
    env_fleet = (os.getenv("OLLAMA_FLEET_KEEP_ALIVE") or "").strip()
    if env_fleet:
        return env_fleet
    return "-1"


def parse_ollama_keep_alive(value) -> int | str | None:
    """Parse Ollama keep_alive from env/CLI values.

    Returns:
        - ``-1`` — keep loaded indefinitely (Ollama native)
        - ``0`` — unload immediately after the request
        - duration strings such as ``5m``, ``30m``
        - positive integers — seconds
        - ``None`` when unset/empty
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.lower()
    if normalized in _FOREVER_ALIASES:
        return -1
    if normalized in _IMMEDIATE_UNLOAD_ALIASES:
        return 0
    try:
        return int(raw)
    except ValueError:
        return raw
