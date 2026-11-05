"""Request bodies for the coordination API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1)
    kind: str = "code"
    goal: str = ""
    acceptance: str = ""
    scope_paths: list[str] = Field(default_factory=list)
    capabilities_required: list[str] = Field(default_factory=list)
    priority: int = 3
    lease_minutes: int | None = None


class ClaimRequest(BaseModel):
    branch: str | None = None
    base_sha: str | None = None


class HandoffRequest(BaseModel):
    to_agent: str
    acceptance_cmd: str
    branch: str | None = None
    summary: str = ""
    open_questions: str = ""


class AcceptHandoffRequest(BaseModel):
    ran: bool = False
    output: str = ""


class ReviewRequest(BaseModel):
    pr_url: str = ""
    evidence: str


class DecideReviewRequest(BaseModel):
    approved: bool
    note: str = ""


class MessageCreate(BaseModel):
    body: str = Field(min_length=1)
    to_agent: str | None = None
    kind: str = "notice"
    task_id: str | None = None
    thread_id: str | None = None


class AgentCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    person: str = ""
    display_name: str = ""
    capabilities: list[str] = Field(default_factory=list)
