"""Structured output of the agent (docs/API_CONTRACT.md §3) and the events it streams."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    text: str
    source: str = Field(description="Tool name the evidence came from")
    verified: bool = True


class Unverified(BaseModel):
    text: str
    how_to_check: str = ""


class DiagnosisAnswer(BaseModel):
    """Prose fields are Vietnamese; resource ids, commands and AWS error codes stay verbatim."""

    summary: str
    cause: str
    evidence: list[Evidence] = []
    fix_steps: list[str] = []
    unverified: list[Unverified] = []
    confidence: Literal["high", "medium", "low"] = "low"


class AgentEvent(BaseModel):
    type: Literal["status", "tool_call", "tool_result", "answer", "error", "done"]
    data: dict[str, Any] = {}


def status(text: str) -> AgentEvent:
    return AgentEvent(type="status", data={"text": text})


def done() -> AgentEvent:
    return AgentEvent(type="done", data={})


def error(code: str, message: str) -> AgentEvent:
    return AgentEvent(type="error", data={"error": code, "message": message})
