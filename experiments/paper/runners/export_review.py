from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def export_run_spreadsheet(
    run_dir: Path,
    builder_fn: Callable[[Path], Path],
    *,
    strict: bool,
) -> Path | None:
    """Invoke a run-dir spreadsheet builder, honoring warn-vs-strict policy."""
    run_dir = Path(run_dir)
    try:
        return Path(builder_fn(run_dir))
    except Exception:
        if strict:
            raise
        logger.warning(
            "Spreadsheet export failed for %s; continuing without team_review.xlsx",
            run_dir,
            exc_info=True,
        )
        return None
