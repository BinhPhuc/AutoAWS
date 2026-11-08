"""Check every piece of evidence against the tool results the server really saw.

The model's own ``verified`` flag is not trusted (AGENTS.md hard constraint #6): an
evidence item counts as ``read`` only if the tool it cites ran successfully in this
conversation and, when it quotes a resource id, that id appears in the tool's output.
See docs/API_CONTRACT.md §3.
"""

from app.agent.schemas import DiagnosisAnswer, Evidence, Verification

# Sources that mean "not from AWS": the user's own statement.
_USER_SOURCES = {"user", "người dùng", "nguoi dung", "question"}


class ToolOutputs:
    """Successful tool results of a conversation, by tool name.

    ``None`` stands for a result whose content is unknown (stored before outputs were
    kept); the tool is known to have run, but its resource ids cannot be checked.
    """

    def __init__(self) -> None:
        self._by_tool: dict[str, list[str | None]] = {}

    def add(self, tool: str, output_json: str | None) -> None:
        self._by_tool.setdefault(tool, []).append(
            output_json.lower() if output_json is not None else None
        )

    def ran(self, tool: str) -> bool:
        return tool in self._by_tool

    def mentions(self, tool: str, needle: str) -> bool:
        needle = needle.lower()
        return any(out is None or needle in out for out in self._by_tool.get(tool, []))


def check(evidence: Evidence, outputs: ToolOutputs, tool_names: set[str]) -> Verification:
    if not evidence.verified:
        return "inferred"
    source = evidence.source.strip()
    if source.lower() in _USER_SOURCES:
        return "inferred"
    if source not in tool_names or not outputs.ran(source):
        return "not_found"
    resource_id = (evidence.resource_id or "").strip()
    if resource_id and not outputs.mentions(source, resource_id):
        return "not_found"
    return "read"


def verify_answer(
    answer: DiagnosisAnswer, outputs: ToolOutputs, tool_names: set[str]
) -> DiagnosisAnswer:
    for cause in answer.root_causes:
        for evidence in cause.evidence:
            evidence.verification = check(evidence, outputs, tool_names)
            evidence.verified = evidence.verification == "read"
    return answer
