"""The agent loop: plan -> call tools -> analyze -> conclude, streamed as AgentEvents.

Blocking boto3 calls run in a worker thread so the SSE stream keeps flowing.

- The model ends a turn with the ``submit_diagnosis`` tool (plain JSON text is accepted
  too); every evidence item is then checked against the tool results (app.agent.evidence).
- Tool results are cached per conversation (same tool + same input, TOOL_CACHE_TTL_SECONDS);
  the model can bypass the cache with ``refresh: true``.
- Limits per turn: iterations, wall-clock time, tokens, tool calls. When one is hit the model
  gets one last round to submit what it confirmed (``limit_reached`` in the answer).
See docs/API_CONTRACT.md §3–§4.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from pydantic import ValidationError

from app.agent import schemas as ev
from app.agent.evidence import ToolOutputs, verify_answer
from app.agent.prompts import (
    ANSWER_FORMAT,
    FINALIZE_PROMPT,
    RETRY_ANSWER_PROMPT,
    SYSTEM_PROMPT,
    context_block,
)
from app.agent.schemas import (
    SUBMIT_INPUT_SCHEMA,
    SUBMIT_TOOL_NAME,
    AgentEvent,
    DiagnosisAnswer,
    LimitReached,
    RootCause,
)
from app.aws.registry import ToolContext, ToolSpec, list_tools, run_tool, summarize_output
from app.aws.tools.dns import hostnames_in
from app.config import Settings, get_settings
from app.llm.base import LLMError, LLMMessage, LLMProvider, LLMResponse, ToolCallRequest
from app.sanitizer import sanitize
from app.storage.base import Store
from app.storage.models import Conversation, Message, ToolCallRecord

log = logging.getLogger(__name__)


STOPPED_NOTE = "Lượt chẩn đoán đã bị dừng trước khi có kết luận."

# A tool result larger than this is re-sanitized with shorter lists before the LLM sees it.
MAX_RESULT_CHARS = 24_000
# What is kept per tool call / per turn in storage (DynamoDB items max out at 400 KB).
MAX_STORED_OUTPUT_CHARS = 16_000
MAX_STORED_TURN_CHARS = 200_000
# Tools whose results contain hostnames resolve_dns_public may look up.
_HOSTNAME_SOURCES = {"route53_list_records", "elbv2_describe_load_balancers", "resolve_dns_public"}

SUBMIT_TOOL = ToolSpec(
    name=SUBMIT_TOOL_NAME,
    group="answer",
    label="Submit diagnosis",
    description="Submit the final diagnosis. Call it once, when you have enough evidence (or "
    "when told to stop). The server checks every evidence item against the tool results.",
    input_schema=SUBMIT_INPUT_SCHEMA,
    aws_actions=[],
    fn=lambda session, params: {},
)

_REFRESH_PARAM = {
    "type": "boolean",
    "description": "Bypass the conversation cache and read live data (use when the user says "
    "they just changed something)",
}

_LIMIT_TEXT = {
    "max_iterations": "the maximum number of reasoning steps",
    "time": "the time limit",
    "tokens": "the token budget",
    "tool_calls": "the maximum number of tool calls",
}


def llm_tools(tools: list[ToolSpec]) -> list[ToolSpec]:
    """What the model sees: the read tools (plus `refresh`) and submit_diagnosis."""
    out = []
    for spec in tools:
        schema = dict(spec.input_schema)
        schema["properties"] = {**schema.get("properties", {}), "refresh": _REFRESH_PARAM}
        out.append(replace(spec, input_schema=schema))
    return [*out, SUBMIT_TOOL]


@dataclass
class _Entry:
    output: dict
    read_at: datetime


class ToolCache:
    """Successful tool results of one conversation, keyed by tool + canonical input."""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl = ttl_seconds
        self._entries: dict[str, _Entry] = {}

    @staticmethod
    def key(tool: str, params: dict) -> str:
        return json.dumps([tool, params], sort_keys=True, default=str)

    def get(self, tool: str, params: dict) -> _Entry | None:
        if self.ttl <= 0:
            return None
        entry = self._entries.get(self.key(tool, params))
        if entry and (datetime.now(UTC) - entry.read_at).total_seconds() <= self.ttl:
            return entry
        return None

    def put(self, tool: str, params: dict, output: dict, read_at: datetime) -> None:
        self._entries[self.key(tool, params)] = _Entry(output, read_at)


async def run_agent(
    store: Store,
    conversation: Conversation,
    question: str,
    aws_session: boto3.Session,
    provider: LLMProvider,
) -> AsyncIterator[AgentEvent]:
    settings = get_settings()
    registry_tools = list_tools()
    tool_index = {t.name: t for t in registry_tools}
    tools = llm_tools(registry_tools)

    prior = [(m, store.list_tool_calls(m.id)) for m in store.list_messages(conversation.id)]
    store.add_message(Message(conversation_id=conversation.id, role="user", content=question))
    store.touch_conversation(conversation, title=question[:80])

    # What earlier turns already read: cache, evidence checks, DNS guard.
    cache = ToolCache(settings.tool_cache_ttl_seconds)
    outputs = ToolOutputs()
    ctx = ToolContext(
        user_text="\n".join([m.content for m, _ in prior if m.role == "user"] + [question])
    )
    for _, calls in prior:
        for c in calls:
            if c.status != "ok" or c.cached:
                continue
            outputs.add(c.tool, c.output_json)
            if c.output_json and c.read_at:
                stored = json.loads(c.output_json)
                cache.put(c.tool, json.loads(c.input_json or "{}"), stored, _aware(c.read_at))
                if c.tool in _HOSTNAME_SOURCES:
                    ctx.known_hostnames |= hostnames_in(c.output_json)

    conn = store.get_connection(conversation.connection_id)
    messages = [LLMMessage(role="system", content=SYSTEM_PROMPT + ANSWER_FORMAT)]
    messages += _history(prior)
    context = _context(settings, aws_session, conn.account_id if conn else None)
    messages.append(LLMMessage(role="user", content=f"{context}\n[Question]\n{question}"))

    records: list[ToolCallRecord] = []
    stored_chars = 0
    started = time.monotonic()
    enforce_time = getattr(provider, "enforce_time_limit", True)
    rounds = tokens = aws_calls = 0
    limit: LimitReached | None = None
    finalize_sent = False  # the next provider call is the last one
    retried_answer = False
    # Set once the assistant message of this turn is stored. If the turn ends any other way
    # (client disconnect / Stop, unexpected error) the finally block stores a note, so the
    # history stays user/assistant and the tool timeline survives a reload.
    finished = False
    thinking = "Waiting for the MCP client…" if provider.name == "mcp" else "Reasoning…"

    def out_of_time() -> bool:
        return (
            enforce_time
            and settings.max_agent_seconds > 0
            and time.monotonic() - started >= settings.max_agent_seconds
        )

    def store_answer(answer: DiagnosisAnswer) -> AgentEvent:
        nonlocal finished
        answer = verify_answer(answer, outputs, set(tool_index))
        answer.limit_reached = limit
        assistant_msg = store.add_message(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=answer.summary,
                answer_json=answer.model_dump_json(),
            ),
            records,
        )
        store.touch_conversation(conversation)
        finished = True
        return AgentEvent(
            type="answer",
            data={
                "message_id": assistant_msg.id,
                "content": answer.summary,
                "answer": answer.model_dump(),
            },
        )

    def fail(code: str, message: str, note: str) -> list[AgentEvent]:
        nonlocal finished
        _save_unfinished(store, conversation, records, note)
        finished = True
        return [ev.error(code, message), ev.done()]

    try:
        while True:
            if limit is None:
                limit = _limit_hit(settings, rounds, tokens, out_of_time())
            if limit is not None and not finalize_sent:
                finalize_sent = True
                messages.append(
                    LLMMessage(
                        role="user", content=FINALIZE_PROMPT.format(reason=_LIMIT_TEXT[limit])
                    )
                )

            yield ev.status(thinking)
            try:
                response = await provider.chat(messages, tools)
            except (LLMError, NotImplementedError) as e:
                message = f"LLM provider is unavailable: {e}"
                for event in fail(
                    "LLM_UNAVAILABLE", message, f"Chưa hoàn thành chẩn đoán: {message}"
                ):
                    yield event
                return
            except Exception as e:  # noqa: BLE001 — never leak a traceback into the stream
                log.exception("LLM call failed")
                message = f"LLM call failed: {type(e).__name__}"
                for event in fail(
                    "LLM_UNAVAILABLE", message, f"Chưa hoàn thành chẩn đoán: {message}"
                ):
                    yield event
                return
            rounds += 1
            tokens += response.input_tokens + response.output_tokens

            # ---- final answer through the submit tool --------------------------------
            submit = next((c for c in response.tool_calls if c.name == SUBMIT_TOOL_NAME), None)
            if submit is not None:
                answer, problem = _answer_from_input(submit.input)
                if answer is not None:
                    yield ev.status("Analyzing results…")
                    yield store_answer(answer)
                    yield ev.done()
                    return
                if finalize_sent:
                    for event in _fail_limit(fail, settings, limit or "max_iterations"):
                        yield event
                    return
                # Let the model fix its answer; every tool call needs a result.
                messages.append(_assistant(response))
                for call in response.tool_calls:
                    error = (
                        f"INVALID_ANSWER: {problem}"
                        if call is submit
                        else "SKIPPED: submit_diagnosis was called in the same step"
                    )
                    messages.append(_tool_message(call, json.dumps({"error": error}), True))
                continue

            # ---- more AWS data -------------------------------------------------------
            if response.wants_tools:
                if finalize_sent:
                    # Told to stop and still wants to read: give up with what we have.
                    for event in _fail_limit(fail, settings, limit or "max_iterations"):
                        yield event
                    return
                messages.append(_assistant(response))
                for call in response.tool_calls:
                    spec = tool_index.get(call.name)
                    params = dict(call.input or {})
                    refresh = bool(params.pop("refresh", False))
                    yield ev.status(f"Reading {spec.label.lower() if spec else call.name}…")
                    yield AgentEvent(
                        type="tool_call",
                        data={"id": call.id, "tool": call.name, "input": params},
                    )

                    if limit is None and aws_calls >= settings.max_tool_calls:
                        limit = "tool_calls"
                    if limit is None and out_of_time():
                        limit = "time"

                    cached = False
                    duration_ms = 0
                    read_at = datetime.now(UTC)
                    hit = None if (refresh or limit) else cache.get(call.name, params)
                    if limit is not None:
                        skip = f"SKIPPED: {_LIMIT_TEXT[limit]} was reached"
                        output, status, error = {"error": skip}, "error", skip
                    elif hit is not None:
                        age = int((read_at - hit.read_at).total_seconds())
                        output = {
                            **hit.output,
                            "_cached": {"read_at": hit.read_at.isoformat(), "age_seconds": age},
                        }
                        status, error, cached, read_at = "ok", None, True, hit.read_at
                    else:
                        result = await asyncio.to_thread(
                            run_tool, aws_session, call.name, params, ctx
                        )
                        aws_calls += 1
                        output = _fit(result.output)
                        status, error = result.status, result.error
                        duration_ms = result.duration_ms
                        if status == "ok":
                            cache.put(call.name, params, output, read_at)

                    output_json = json.dumps(output, default=str, ensure_ascii=False)
                    keep = False
                    if status == "ok" and not cached:
                        outputs.add(call.name, output_json)
                        if call.name in _HOSTNAME_SOURCES:
                            ctx.known_hostnames |= hostnames_in(output_json)
                        keep = (
                            len(output_json) <= MAX_STORED_OUTPUT_CHARS
                            and stored_chars + len(output_json) <= MAX_STORED_TURN_CHARS
                        )
                        stored_chars += len(output_json) if keep else 0
                    summary = summarize_output(output)
                    records.append(
                        ToolCallRecord(
                            tool=call.name,
                            input_json=json.dumps(params, default=str),
                            output_summary=summary,
                            status=status,
                            error=error,
                            duration_ms=duration_ms,
                            output_json=output_json if keep else None,
                            read_at=read_at,
                            cached=cached,
                        )
                    )
                    yield AgentEvent(
                        type="tool_result",
                        data={
                            "id": call.id,
                            "status": status,
                            "output_summary": summary,
                            "duration_ms": duration_ms,
                            "cached": cached,
                        },
                    )
                    messages.append(_tool_message(call, output_json, status == "error"))
                continue

            # ---- plain text: JSON answer from a provider without tools, or a slip ----------
            answer = _parse_answer(response.text or "")
            if answer is not None:
                yield ev.status("Analyzing results…")
                yield store_answer(answer)
                yield ev.done()
                return
            if finalize_sent:
                for event in _fail_limit(fail, settings, limit or "max_iterations"):
                    yield event
                return
            if not retried_answer:
                retried_answer = True
                messages.append(_assistant(response))
                messages.append(LLMMessage(role="user", content=RETRY_ANSWER_PROMPT))
                continue
            yield ev.status("Analyzing results…")
            yield store_answer(_fallback_answer(response.text or ""))
            yield ev.done()
            return
    finally:
        if not finished:
            try:
                _save_unfinished(store, conversation, records, STOPPED_NOTE)
            except Exception:  # noqa: BLE001 — do not mask the original exit reason
                log.exception("Could not store the unfinished turn")


# ---------------------------------------------------------------------------


def _limit_hit(
    settings: Settings, rounds: int, tokens: int, timed_out: bool
) -> LimitReached | None:
    if rounds >= settings.max_agent_iterations:
        return "max_iterations"
    if timed_out:
        return "time"
    if settings.max_turn_tokens > 0 and tokens >= settings.max_turn_tokens:
        return "tokens"
    return None


def _fail_limit(
    fail: Callable[[str, str, str], list[AgentEvent]], settings: Settings, limit: LimitReached
) -> list[AgentEvent]:
    if limit == "max_iterations":
        n = settings.max_agent_iterations
        return fail(
            "MAX_ITERATIONS",
            f"Stopped after {n} reasoning steps without a conclusion",
            f"Chưa hoàn thành chẩn đoán: dừng sau {n} bước suy luận mà chưa có kết luận.",
        )
    detail = {
        "time": (
            f"the time limit ({settings.max_agent_seconds} s)",
            f"hết thời gian cho phép ({settings.max_agent_seconds} giây)",
        ),
        "tokens": (
            f"the token budget ({settings.max_turn_tokens} tokens)",
            f"hết ngân sách token ({settings.max_turn_tokens} token)",
        ),
        "tool_calls": (
            f"the tool call budget ({settings.max_tool_calls} calls)",
            f"hết số lần gọi công cụ cho phép ({settings.max_tool_calls} lần)",
        ),
    }[limit]
    return fail(
        "AGENT_LIMIT",
        f"Stopped at {detail[0]} without a conclusion",
        f"Chưa hoàn thành chẩn đoán: {detail[1]} mà chưa có kết luận.",
    )


def _save_unfinished(
    store: Store, conversation: Conversation, records: list[ToolCallRecord], note: str
) -> None:
    """Store an assistant message without answer for a turn that ended early."""
    store.add_message(
        Message(conversation_id=conversation.id, role="assistant", content=note),
        records,
    )
    store.touch_conversation(conversation)


def _assistant(response: LLMResponse) -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=response.text or "",
        tool_calls=response.tool_calls,
        raw=response.raw,
    )


def _tool_message(call: ToolCallRequest, content: str, is_error: bool) -> LLMMessage:
    return LLMMessage(
        role="tool",
        tool_call_id=call.id,
        tool_name=call.name,
        content=content,
        is_error=is_error,
    )


def _fit(raw: dict) -> dict:
    """Sanitize a tool result and keep it small enough for the model's context."""
    clean = sanitize(raw)
    if len(json.dumps(clean, default=str)) <= MAX_RESULT_CHARS:
        return clean
    for items in (8, 3):
        smaller = sanitize(raw, max_list_items=items)
        if len(json.dumps(smaller, default=str)) <= MAX_RESULT_CHARS:
            return {
                **smaller,
                "_note": f"result shortened (lists cut to {items} items); narrow the query "
                "with ids or filters to see everything",
            }
    return {
        "_note": "result too large to show; narrow the query with ids or filters",
        "summary": summarize_output(clean),
    }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _context(settings: Settings, session: boto3.Session, account: str | None) -> str:
    try:
        tz, tz_name = ZoneInfo(settings.user_timezone), settings.user_timezone
    except (ZoneInfoNotFoundError, ValueError):
        tz, tz_name = UTC, "UTC"
    now = datetime.now(UTC)
    return context_block(
        now_local=now.astimezone(tz).isoformat(timespec="seconds"),
        now_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        timezone=tz_name,
        region=session.region_name or "unknown",
        account=account or "unknown",
    )


def _history(prior: list[tuple[Message, list[ToolCallRecord]]]) -> list[LLMMessage]:
    """Replay earlier turns so follow-up questions reuse what was already read."""
    out: list[LLMMessage] = []
    for m, calls in prior:
        if m.role == "user":
            out.append(LLMMessage(role="user", content=m.content))
            continue
        read = "\n".join(f"- {c.tool} {c.input_json}: {c.output_summary}" for c in calls)
        body = m.answer_json or m.content
        if read:
            body = (
                "[Data read earlier]\n"
                "(the same tool with the same input is served from the cache for a few minutes)\n"
                f"{read}\n\n[Answer]\n{body}"
            )
        out.append(LLMMessage(role="assistant", content=body))
    return out


def _answer_from_input(data: dict) -> tuple[DiagnosisAnswer | None, str]:
    try:
        return DiagnosisAnswer.model_validate(data or {}), ""
    except ValidationError as e:
        problems = [
            f"{'.'.join(str(p) for p in err['loc']) or 'answer'}: {err['msg']}"
            for err in e.errors()[:5]
        ]
        return None, "; ".join(problems)


def _parse_answer(text: str) -> DiagnosisAnswer | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return DiagnosisAnswer.model_validate_json(text[start : end + 1])
    except ValueError:
        return None


def _fallback_answer(text: str) -> DiagnosisAnswer:
    return DiagnosisAnswer(
        summary="Mô hình trả lời không đúng định dạng; dưới đây là nội dung thô.",
        root_causes=[RootCause(statement=text[:1500] or "Không có nội dung.", confidence="low")],
        confidence="low",
    )
