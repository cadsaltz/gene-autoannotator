from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

JobProgressPhase = Literal[
    "fetching",
    "extracting",
    "aggregating",
    "go_resolving",
    "ortholog_fetching",
    "ortholog_extracting",
    "ortholog_aggregating",
    "ortholog_go_resolving",
    "finalizing",
]

PassName = Literal["target", "ortholog"]


class JobProgressEvent(BaseModel):
    job_id: str | None = None
    phase: JobProgressPhase
    sections_done: int = Field(default=0, ge=0)
    sections_total: int | None = Field(default=None, ge=0)
    papers_done: int | None = Field(default=None, ge=0)
    papers_total: int | None = Field(default=None, ge=0)
    pass_name: PassName | None = None
    message: str | None = None


def format_current_step(event: JobProgressEvent) -> str:
    if event.message:
        return event.message
    total = event.sections_total if event.sections_total is not None else "?"
    base = f"{event.phase} {event.sections_done}/{total} sections"
    if event.pass_name:
        return f"{base} ({event.pass_name})"
    return base
