"""Structured output of the agent (docs/API_CONTRACT.md §3) and the events it streams."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.aws.remediation.catalog import CATALOG

Confidence = Literal["high", "medium", "low"]
Verification = Literal["read", "inferred", "not_found"]
LimitReached = Literal["max_iterations", "time", "tokens", "tool_calls"]


class Evidence(BaseModel):
    # Models sometimes quote numbers (a port, a count) as JSON numbers.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    text: str
    source: str = Field(description="Tool name the evidence came from, or 'user'")
    resource_id: str | None = None
    field: str | None = None
    value: str | None = None
    verified: bool = True
    # Set by the server (app.agent.evidence) from the tool results it really saw.
    verification: Verification | None = None


class RootCause(BaseModel):
    statement: str
    confidence: Confidence = "medium"
    evidence: list[Evidence] = []


class Unverified(BaseModel):
    text: str
    how_to_check: str = ""


class ProposalRef(BaseModel):
    """A remediation the model proposes (catalogue action + params). The server fills
    proposal_id when it stored a PENDING proposal, or error when it refused it."""

    action: str
    params: dict = {}
    reason: str = ""
    proposal_id: str | None = None
    error: str | None = None


class DiagnosisAnswer(BaseModel):
    """Prose fields are Vietnamese; resource ids, commands and AWS error codes stay verbatim."""

    summary: str
    root_causes: list[RootCause] = []
    fix_steps: list[str] = []
    unverified: list[Unverified] = []
    confidence: Confidence = "low"
    proposals: list[ProposalRef] = []
    # Set by the agent loop when it had to stop early (docs/API_CONTRACT.md §3).
    limit_reached: LimitReached | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        # Answers stored before root_causes existed: one `cause` + top-level `evidence`.
        if "root_causes" not in data and "cause" in data:
            cause = data.pop("cause")
            evidence = data.pop("evidence", None) or []
            data["root_causes"] = (
                [
                    {
                        "statement": cause,
                        "confidence": data.get("confidence", "low"),
                        "evidence": evidence,
                    }
                ]
                if cause
                else []
            )
        # Tolerate plain strings where an object is expected.
        if isinstance(data.get("unverified"), list):
            data["unverified"] = [
                {"text": u} if isinstance(u, str) else u for u in data["unverified"]
            ]
        if isinstance(data.get("root_causes"), list):
            data["root_causes"] = [
                {"statement": rc} if isinstance(rc, str) else rc for rc in data["root_causes"]
            ]
        return data


SUBMIT_TOOL_NAME = "submit_diagnosis"

_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The evidence, in Vietnamese"},
        "source": {
            "type": "string",
            "description": "Name of the tool whose result shows this, or 'user' if only the "
            "user said it",
        },
        "resource_id": {"type": "string", "description": "AWS resource id quoted, e.g. rtb-0abc"},
        "field": {"type": "string", "description": "Field of the tool result, e.g. routes"},
        "value": {
            "type": "string",
            "description": "The exact value read, e.g. '10.0.0.0/16 -> local'",
        },
        "verified": {
            "type": "boolean",
            "description": "false if this is inferred rather than read from a tool result",
        },
    },
    "required": ["text", "source"],
}

# Input of the submit_diagnosis tool: DiagnosisAnswer without the server-set fields.
SUBMIT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "1-2 sentences in Vietnamese"},
        "root_causes": {
            "type": "array",
            "description": "One item per independent problem, most blocking first. Empty if "
            "nothing wrong was found.",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string", "description": "The cause, in Vietnamese"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence": {"type": "array", "items": _EVIDENCE_SCHEMA},
                },
                "required": ["statement", "confidence", "evidence"],
            },
        },
        "fix_steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete steps in Vietnamese; keep ids and commands verbatim",
        },
        "unverified": {
            "type": "array",
            "description": "What AWS data could not confirm, each with a check the user can run",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "how_to_check": {"type": "string"},
                },
                "required": ["text", "how_to_check"],
            },
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "proposals": {
            "type": "array",
            "maxItems": 5,
            "description": "Optional: fixes from the remediation catalogue the user can approve "
            "with one click. Only catalogue actions; the user approves each one.",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": sorted(CATALOG)},
                    "params": {"type": "object", "description": "As the catalogue describes"},
                    "reason": {"type": "string", "description": "Why, in Vietnamese"},
                },
                "required": ["action", "params", "reason"],
            },
        },
    },
    "required": ["summary", "root_causes", "fix_steps", "unverified", "confidence"],
}


class AgentEvent(BaseModel):
    type: Literal["status", "tool_call", "tool_result", "answer", "error", "done"]
    data: dict[str, Any] = {}


def status(text: str) -> AgentEvent:
    return AgentEvent(type="status", data={"text": text})


def done() -> AgentEvent:
    return AgentEvent(type="done", data={})


def error(code: str, message: str) -> AgentEvent:
    return AgentEvent(type="error", data={"error": code, "message": message})
