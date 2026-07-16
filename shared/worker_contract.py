from typing import Literal

from pydantic import BaseModel, Field

from shared.job_contract import AnnotationJobRequest

WorkerState = Literal["provisioning", "ready", "draining", "offline"]


class WorkerRegister(BaseModel):
    worker_name: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    total_memory_bytes: int = Field(ge=0)
    dedicated_memory_bytes: int = Field(ge=0)
    max_slots: int = Field(ge=0)
    ollama_models: list[str] = Field(default_factory=list)


class WorkerRegisterResponse(BaseModel):
    worker_id: str


class WorkerHeartbeat(BaseModel):
    active_jobs: int = Field(ge=0)
    free_slots: int = Field(ge=0)
    memory_available_bytes: int = Field(ge=0)
    cpu_percent: float = 0.0
    state: WorkerState = "ready"


class HeartbeatResponse(BaseModel):
    required_version: str | None = None
    drain: bool = False


class ClaimRequest(BaseModel):
    free_slots: int = Field(ge=0)


class ClaimResponse(BaseModel):
    job_id: str
    request: AnnotationJobRequest
    lease_expires_at: str


class JobProgress(BaseModel):
    current_step: str = Field(min_length=1)
    phase: str | None = None
    sections_done: int | None = Field(default=None, ge=0)
    sections_total: int | None = Field(default=None, ge=0)
    papers_done: int | None = Field(default=None, ge=0)
    papers_total: int | None = Field(default=None, ge=0)
    pass_name: str | None = None


class JobComplete(BaseModel):
    result: dict


class JobFail(BaseModel):
    error: str
    retryable: bool = True
