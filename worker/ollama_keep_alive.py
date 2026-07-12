from __future__ import annotations

_FOREVER_ALIASES = frozenset(
    {"-1", "forever", "infinite", "inf", "infinity", "never", "permanent"}
)
_IMMEDIATE_UNLOAD_ALIASES = frozenset({"0", "false", "no", "unload", "immediate"})


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
