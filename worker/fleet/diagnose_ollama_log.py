"""CLI: summarize an Ollama serve log file.

Usage:
  python -m worker.fleet.diagnose_ollama_log path/to/ollama-server-11434.log
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from worker.fleet.ollama_diag import format_summary_lines, summarize_ollama_lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize an Ollama serve log for diagnostics.")
    parser.add_argument("log_path", type=Path, help="Path to ollama-server-*.log")
    args = parser.parse_args(argv)
    path: Path = args.log_path
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    summary = summarize_ollama_lines(lines)
    print(f"log: {path}")
    for line in format_summary_lines(summary):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
