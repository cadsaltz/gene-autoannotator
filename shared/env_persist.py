import os
import re
from pathlib import Path

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def save_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={values[key]}" for key in sorted(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_value(
    key: str,
    *,
    env_file: Path,
    cli_value: str | None = None,
    prompt_fn=None,
    default: str | None = None,
) -> tuple[str, str]:
    """Return (value, source). source is cli|env|file|default|prompt."""
    file_values = load_env_file(env_file)
    if cli_value is not None and cli_value != "":
        file_values[key] = cli_value
        save_env_file(env_file, file_values)
        return cli_value, "cli"
    if key in os.environ and os.environ[key]:
        return os.environ[key], "env"
    if key in file_values and file_values[key]:
        return file_values[key], "file"
    if default is not None:
        file_values[key] = default
        save_env_file(env_file, file_values)
        return default, "default"
    if prompt_fn is not None:
        value = prompt_fn(key, default)
        if not value:
            raise ValueError(f"{key} is required")
        file_values[key] = value
        save_env_file(env_file, file_values)
        return value, "prompt"
    raise ValueError(f"{key} is required")
