"""Agent loop features: submit_diagnosis, evidence checks, input validation, cache, limits."""

import asyncio
import json

from app.agent.loop import run_agent
from app.agent.schemas import SUBMIT_TOOL_NAME, DiagnosisAnswer
from app.aws.registry import run_tool
from app.llm.base import LLMResponse, ToolCallRequest
from app.storage.models import Conversation


class Scripted:
    """Provider driven by a script: step(messages, round_no) -> LLMResponse."""

    name = "scripted"
    enforce_time_limit = True

    def __init__(self, step):
        self.step = step
        self.seen: list[list] = []

    async def chat(self, messages, tools):
        self.seen.append(list(messages))
        result = self.step(messages, len(self.seen))
        if asyncio.iscoroutine(result):
            result = await result
        return result


def tools(*calls: tuple[str, dict]) -> LLMResponse:
    return LLMResponse(
        tool_calls=[
            ToolCallRequest(id=f"c{i}_{name}", name=name, input=params)
            for i, (name, params) in enumerate(calls)
        ],
        stop_reason="tool_use",
    )


def submit(answer: dict) -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCallRequest(id="final", name=SUBMIT_TOOL_NAME, input=answer)],
        stop_reason="tool_use",
    )


def answer(*evidence: dict, summary: str = "Tóm tắt") -> dict:
    return {
        "summary": summary,
        "root_causes": [
            {"statement": "Nguyên nhân", "confidence": "high", "evidence": list(evidence)}
        ],
        "fix_steps": ["Sửa"],
        "unverified": [],
        "confidence": "high",
    }


async def _run(store, aws, provider, question="Không SSH được", conv=None):
    conv = conv or store.create_conversation(Conversation(connection_id="conn_feat"))
    events = [e async for e in run_agent(store, conv, question, aws, provider)]
    return conv, events


def _answer(events) -> dict:
    return next(e.data["answer"] for e in events if e.type == "answer")


def _instance(aws) -> str:
    ec2 = aws.client("ec2")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    return ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1, SubnetId=subnet)[
        "Instances"
    ][0]["InstanceId"]


# ---- evidence checks -------------------------------------------------------------


async def test_evidence_is_checked_against_tool_results(store, aws):
    instance_id = _instance(aws)

    def step(messages, n):
        if n == 1:
            return tools(("describe_instances", {}))
        return submit(
            answer(
                {"text": "đọc được", "source": "describe_instances", "resource_id": instance_id},
                {
                    "text": "ID bịa",
                    "source": "describe_instances",
                    "resource_id": "i-0doesnotexist",
                },
                {"text": "chưa gọi", "source": "describe_route_tables", "resource_id": "rtb-1"},
                {"text": "suy luận", "source": "describe_instances", "verified": False},
                {"text": "người dùng nói", "source": "user"},
                {"text": "tool không tồn tại", "source": "describe_everything"},
            )
        )

    _, events = await _run(store, aws, Scripted(step))
    got = [
        (e["text"], e["verification"], e["verified"])
        for e in _answer(events)["root_causes"][0]["evidence"]
    ]
    assert got == [
        ("đọc được", "read", True),
        ("ID bịa", "not_found", False),
        ("chưa gọi", "not_found", False),
        ("suy luận", "inferred", False),
        ("người dùng nói", "inferred", False),
        ("tool không tồn tại", "not_found", False),
    ]


async def test_follow_up_evidence_can_cite_data_read_in_an_earlier_turn(store, aws):
    instance_id = _instance(aws)
    first = Scripted(lambda m, n: tools(("describe_instances", {})) if n == 1 else submit(answer()))
    conv, _ = await _run(store, aws, first)
    cite = {"text": "từ lượt trước", "source": "describe_instances", "resource_id": instance_id}
    _, events = await _run(store, aws, Scripted(lambda m, n: submit(answer(cite))), conv=conv)
    assert _answer(events)["root_causes"][0]["evidence"][0]["verification"] == "read"


async def test_invalid_submit_gets_one_more_chance(store, aws):
    def step(messages, n):
        if n == 1:
            return submit({"root_causes": "not a list"})  # no summary, wrong type
        last = messages[-1]
        assert last.role == "tool" and last.is_error and "INVALID_ANSWER" in last.content
        return submit(answer(summary="Lần hai"))

    _, events = await _run(store, aws, Scripted(step))
    assert _answer(events)["summary"] == "Lần hai"


async def test_plain_json_text_answer_is_still_accepted(store, aws):
    text = json.dumps(answer(summary="Bằng text"), ensure_ascii=False)
    _, events = await _run(store, aws, Scripted(lambda m, n: LLMResponse(text=text)))
    assert _answer(events)["summary"] == "Bằng text"


def test_legacy_answers_are_upgraded():
    old = {
        "summary": "s",
        "cause": "Route table thiếu 0.0.0.0/0",
        "evidence": [{"text": "chỉ có local", "source": "describe_route_tables"}],
        "fix_steps": [],
        "unverified": ["sshd?"],
        "confidence": "high",
    }
    a = DiagnosisAnswer.model_validate(old)
    assert a.root_causes[0].statement == "Route table thiếu 0.0.0.0/0"
    assert a.root_causes[0].confidence == "high"
    assert a.root_causes[0].evidence[0].source == "describe_route_tables"
    assert a.unverified[0].text == "sshd?"
    assert DiagnosisAnswer.model_validate({"summary": "s", "cause": ""}).root_causes == []


# ---- tool input validation ---------------------------------------------------------


def test_run_tool_rejects_unknown_and_mistyped_parameters(aws):
    r = run_tool(aws, "describe_route_tables", {"subnet_id": "subnet-1"})
    assert r.status == "error"
    assert "unknown parameter(s) subnet_id" in r.error and "subnet_ids" in r.error
    r = run_tool(aws, "describe_instances", {"instance_ids": "i-1"})
    assert r.status == "error" and r.error.startswith("INVALID_INPUT: instance_ids")
    r = run_tool(aws, "cloudtrail_lookup_events", {"hours": 99999})
    assert r.status == "error" and "INVALID_INPUT" in r.error


async def test_invalid_tool_input_reaches_the_model_as_an_error(store, aws):
    def step(messages, n):
        if n == 1:
            return tools(("describe_route_tables", {"subnet_id": "subnet-1"}))
        last = messages[-1]
        assert last.is_error and "INVALID_INPUT" in last.content
        return submit(answer())

    _, events = await _run(store, aws, Scripted(step))
    result = next(e.data for e in events if e.type == "tool_result")
    assert result["status"] == "error" and "INVALID_INPUT" in result["output_summary"]


# ---- conversation cache -----------------------------------------------------------


async def test_same_call_in_a_follow_up_is_served_from_the_cache(store, aws):
    _instance(aws)
    script = lambda m, n: tools(("describe_instances", {})) if n == 1 else submit(answer())  # noqa: E731
    conv, events1 = await _run(store, aws, Scripted(script))
    assert next(e.data for e in events1 if e.type == "tool_result")["cached"] is False

    second = Scripted(script)
    _, events2 = await _run(store, aws, second, conv=conv)
    result = next(e.data for e in events2 if e.type == "tool_result")
    assert result["cached"] is True and result["duration_ms"] == 0
    tool_msg = next(m for m in second.seen[1] if m.role == "tool")
    assert json.loads(tool_msg.content)["_cached"]["age_seconds"] >= 0

    # refresh bypasses the cache; the timeline shows the input without `refresh`
    refresh = Scripted(
        lambda m, n: (
            tools(("describe_instances", {"refresh": True})) if n == 1 else submit(answer())
        )
    )
    _, events3 = await _run(store, aws, refresh, conv=conv)
    call = next(e.data for e in events3 if e.type == "tool_call")
    assert call["input"] == {}
    assert next(e.data for e in events3 if e.type == "tool_result")["cached"] is False

    # stored records: real reads keep their output, cache hits do not duplicate it
    calls = [tc for m in store.list_messages(conv.id) for tc in store.list_tool_calls(m.id)]
    assert [bool(tc.cached) for tc in calls] == [False, True, False]
    assert calls[0].output_json and calls[0].read_at
    assert calls[1].output_json is None


async def test_cache_can_be_disabled(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "tool_cache_ttl_seconds", 0)
    script = lambda m, n: tools(("get_caller_identity", {})) if n == 1 else submit(answer())  # noqa: E731
    conv, _ = await _run(store, aws, Scripted(script))
    _, events = await _run(store, aws, Scripted(script), conv=conv)
    assert next(e.data for e in events if e.type == "tool_result")["cached"] is False


# ---- limits ---------------------------------------------------------------------------


def _stop_requested(messages) -> bool:
    return any(m.role == "user" and m.content.startswith("[Limit reached") for m in messages)


async def test_iteration_limit_lets_the_model_submit_what_it_has(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_agent_iterations", 2)

    def step(messages, n):
        if _stop_requested(messages):
            return submit(answer(summary="Chốt sớm"))
        return tools(("get_caller_identity", {}))

    provider = Scripted(step)
    _, events = await _run(store, aws, provider)
    got = _answer(events)
    assert got["summary"] == "Chốt sớm" and got["limit_reached"] == "max_iterations"
    assert len(provider.seen) == 3  # 2 rounds + the final one


async def test_time_limit(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_agent_seconds", 1)

    async def step(messages, n):
        if _stop_requested(messages):
            return submit(answer(summary="Hết giờ"))
        await asyncio.sleep(1.05)
        return tools(("get_caller_identity", {}))

    _, events = await _run(store, aws, Scripted(step))
    got = _answer(events)
    assert got["limit_reached"] == "time"
    # the call requested after the deadline was skipped, not run
    result = next(e.data for e in events if e.type == "tool_result")
    assert result["status"] == "error" and "SKIPPED" in result["output_summary"]


async def test_tool_call_budget(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_tool_calls", 1)

    def step(messages, n):
        if _stop_requested(messages):
            return submit(answer())
        return tools(("get_caller_identity", {}), ("describe_instances", {}))

    _, events = await _run(store, aws, Scripted(step))
    statuses = [e.data["status"] for e in events if e.type == "tool_result"]
    assert statuses == ["ok", "error"]
    assert _answer(events)["limit_reached"] == "tool_calls"


async def test_token_budget(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_turn_tokens", 1000)

    def step(messages, n):
        if _stop_requested(messages):
            return submit(answer())
        r = tools(("get_caller_identity", {}))
        r.input_tokens, r.output_tokens = 900, 200
        return r

    _, events = await _run(store, aws, Scripted(step))
    assert _answer(events)["limit_reached"] == "tokens"


async def test_model_that_ignores_the_stop_gets_an_error(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_agent_seconds", 1)

    async def step(messages, n):
        await asyncio.sleep(1.05)
        return tools(("get_caller_identity", {}))

    conv, events = await _run(store, aws, Scripted(step))
    err = next(e.data for e in events if e.type == "error")
    assert err["error"] == "AGENT_LIMIT" and "time limit (1 s)" in err["message"]
    assert "hết thời gian" in store.list_messages(conv.id)[1].content


async def test_mcp_provider_is_not_time_limited(store, aws, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_agent_seconds", 1)

    async def step(messages, n):
        if n == 1:
            await asyncio.sleep(1.05)
            return tools(("get_caller_identity", {}))
        return submit(answer())

    provider = Scripted(step)
    provider.enforce_time_limit = False
    _, events = await _run(store, aws, provider)
    assert _answer(events)["limit_reached"] is None


# ---- context -------------------------------------------------------------------------


async def test_question_carries_time_region_and_account(store, aws):
    provider = Scripted(lambda m, n: submit(answer()))
    await _run(store, aws, provider, question="Từ chiều nay web lỗi")
    question = provider.seen[0][-1].content
    assert question.startswith("[Context]\nCurrent time: ")
    assert "Asia/Ho_Chi_Minh" in question and "UTC " in question
    assert "AWS region of this connection: ap-southeast-1" in question
    assert question.endswith("[Question]\nTừ chiều nay web lỗi")
    # submit_diagnosis is offered, and every read tool accepts `refresh`
    assert provider.seen[0][0].role == "system"
