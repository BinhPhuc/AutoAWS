"""MockProvider — lets the whole pipeline run end-to-end without any LLM key.

Turn 1: pick tools from keywords in the user's question.
Turn 2: once tool results are in the conversation, call submit_diagnosis with an answer
that simply lists what was read. It does not reason; its job is to exercise the UI, the
tool layer, evidence checks and the streaming path. Use LLM_PROVIDER=bedrock for real
diagnoses.
"""

import json
import re

from app.agent.schemas import SUBMIT_TOOL_NAME, DiagnosisAnswer, Evidence, RootCause, Unverified
from app.aws.registry import ToolSpec
from app.llm.base import LLMMessage, LLMResponse, ToolCallRequest

# keyword (regex, case-insensitive) -> tool calls
_RULES: list[tuple[str, list[tuple[str, dict]]]] = [
    (
        r"\bssh\b|port 22|\b22/tcp\b|không (vào|truy cập) được (máy|instance)",
        [
            ("describe_instances", {}),
            ("describe_security_groups", {}),
            ("describe_route_tables", {}),
            ("ssm_describe_instance_information", {}),
        ],
    ),
    (
        r"\b50[0-9]\b|5xx|bad gateway|load ?balancer|\balb\b|target|health ?check",
        [
            ("elbv2_describe_load_balancers", {}),
            ("elbv2_describe_target_health", {}),
            (
                "cloudwatch_get_metric_data",
                {"namespace": "AWS/ApplicationELB", "metric_name": "HTTPCode_ELB_5XX_Count"},
            ),
        ],
    ),
    (
        r"\bdns\b|tên miền|domain|route ?53|trỏ|\b[a-z0-9-]+\.[a-z]{2,}\b",
        [
            ("route53_list_records", {}),
            ("describe_instances", {}),
            ("describe_security_groups", {}),
            ("describe_addresses", {}),
        ],
    ),
    (r"\blogs?\b|exception|stack ?trace|lỗi 500", [("logs_describe_log_groups", {})]),
    (
        r"từ (sáng|chiều|tối|hôm)|tự nhiên|đột nhiên|sau khi|suddenly|\bsince\b",
        [("cloudtrail_lookup_events", {})],
    ),
]

_DEFAULT_CALLS: list[tuple[str, dict]] = [
    ("get_caller_identity", {}),
    ("describe_instances", {}),
]

_DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+[a-z]{2,})\b", re.I)


class MockProvider:
    name = "mock"
    enforce_time_limit = True

    async def chat(self, messages: list[LLMMessage], tools: list[ToolSpec]) -> LLMResponse:
        tool_results = [m for m in messages if m.role == "tool"]
        if tool_results:
            answer = self._answer(tool_results, tools)
            call = ToolCallRequest(id="mock_submit", name=SUBMIT_TOOL_NAME, input=answer)
            return LLMResponse(tool_calls=[call], stop_reason="tool_use")

        question = next((m.content for m in reversed(messages) if m.role == "user"), "")
        calls = self._plan(question, tools)
        return LLMResponse(tool_calls=calls, stop_reason="tool_use")

    # -- turn 1 ---------------------------------------------------------------

    def _plan(self, question: str, tools: list[ToolSpec]) -> list[ToolCallRequest]:
        available = {t.name for t in tools}
        chosen: list[tuple[str, dict]] = []
        for pattern, calls in _RULES:
            if re.search(pattern, question, re.I):
                chosen.extend(calls)
        if not chosen:
            chosen = list(_DEFAULT_CALLS)

        domain = _DOMAIN_RE.search(question)
        if domain and "resolve_dns_public" in available:
            chosen.insert(0, ("resolve_dns_public", {"hostname": domain.group(1)}))
            chosen = [
                (n, {**p, "domain": domain.group(1)} if n == "route53_list_records" else p)
                for n, p in chosen
            ]

        seen: set[str] = set()
        requests = []
        for name, params in chosen:
            if name in available and name not in seen:
                seen.add(name)
                requests.append(
                    ToolCallRequest(id=f"mock_{len(requests) + 1}", name=name, input=params)
                )
        return requests

    # -- turn 2 ---------------------------------------------------------------

    def _answer(self, tool_results: list[LLMMessage], tools: list[ToolSpec]) -> dict:
        labels = {t.name: t.label for t in tools}
        evidence: list[Evidence] = []
        unverified: list[Unverified] = []
        for m in tool_results:
            name = m.tool_name or "unknown"
            try:
                data = json.loads(m.content or "{}")
            except json.JSONDecodeError:
                data = {"raw": m.content}
            if isinstance(data, dict) and data.get("error"):
                unverified.append(
                    Unverified(
                        text=f"Không đọc được {labels.get(name, name)}: {data['error']}",
                        how_to_check=f"Kiểm tra quyền IAM cho công cụ {name}",
                    )
                )
                continue
            evidence.append(
                Evidence(
                    text=f"{labels.get(name, name)}: {_describe(data)}",
                    source=name,
                    resource_id=_first_resource_id(data),
                    verified=True,
                )
            )

        answer = DiagnosisAnswer(
            summary="Đây là kết quả từ MockProvider: hệ thống đã đọc dữ liệu AWS thật nhưng "
            "chưa có mô hình ngôn ngữ để suy luận.",
            root_causes=[
                RootCause(
                    statement="MockProvider — chưa cấu hình LLM, chỉ liệt kê bằng chứng chưa suy "
                    "luận. Đặt LLM_PROVIDER=bedrock trong backend/.env để nhận chẩn đoán thật.",
                    confidence="low",
                    evidence=evidence,
                )
            ],
            fix_steps=[
                "Cấu hình LLM provider thật trong backend/.env (xem docs/BACKEND_PLAN.md §4.3).",
                "Xem lại các bằng chứng bên trên để tự đối chiếu theo đường đi kết nối: "
                "DNS → IP → route table → NACL → Security Group → Load Balancer → instance.",
            ],
            unverified=unverified,
            confidence="low",
        )
        return answer.model_dump(exclude={"limit_reached"}, exclude_none=True)


def _describe(data: dict) -> str:
    if not isinstance(data, dict):
        return str(data)[:200]
    parts = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            ids = [_first_id(v) for v in value[:5] if isinstance(v, dict)]
            ids = [i for i in ids if i]
            parts.append(
                f"{len(value)} {key.replace('_', ' ')}" + (f" ({', '.join(ids)})" if ids else "")
            )
        elif isinstance(value, str | int | float | bool):
            parts.append(f"{key}={value}")
    return "; ".join(parts)[:300] or "không có dữ liệu"


def _first_resource_id(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return _first_id(value[0])
    return None


def _first_id(item: dict) -> str | None:
    for key in (
        "instance_id",
        "group_id",
        "route_table_id",
        "subnet_id",
        "acl_id",
        "igw_id",
        "name",
        "arn",
        "hostname",
    ):
        if item.get(key):
            return str(item[key])
    return None
