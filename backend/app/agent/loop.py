"""The agent loop: plan -> call tools -> analyze -> conclude, streamed as AgentEvents.

Blocking boto3 calls run in a worker thread so the SSE stream keeps flowing.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import boto3
from sqlmodel import Session

from app.agent import schemas as ev
from app.agent.prompts import ANSWER_FORMAT, RETRY_JSON_PROMPT, SYSTEM_PROMPT
from app.agent.schemas import AgentEvent, DiagnosisAnswer
from app.aws.registry import ToolSpec, list_tools, run_tool, summarize_output
from app.config import get_settings
from app.llm.base import LLMError, LLMMessage, LLMProvider
from app.sanitizer import sanitize
from app.storage import repo
from app.storage.models import Conversation, Message, ToolCallRecord

log = logging.getLogger(__name__)


STOPPED_NOTE = "Lượt chẩn đoán đã bị dừng trước khi có kết luận."


async def run_agent(
    db: Session,
    conversation: Conversation,
    question: str,
    aws_session: boto3.Session,
    provider: LLMProvider,
) -> AsyncIterator[AgentEvent]:
    settings = get_settings()
    tools = list_tools()
    tool_index = {t.name: t for t in tools}

    user_msg = repo.add_message(
        db, Message(conversation_id=conversation.id, role="user", content=question)
    )
    repo.touch_conversation(db, conversation, title=question[:80])

    messages = [LLMMessage(role="system", content=SYSTEM_PROMPT + ANSWER_FORMAT)]
    messages += _history(db, conversation.id, exclude_id=user_msg.id)
    messages.append(LLMMessage(role="user", content=question))

    records: list[ToolCallRecord] = []
    retried_json = False
    # Set once the assistant message of this turn is stored. If the turn ends any other way
    # (client disconnect / Stop, unexpected error) the finally block stores a note, so the
    # history stays user/assistant and the tool timeline survives a reload.
    finished = False
    thinking = "Waiting for the MCP client…" if provider.name == "mcp" else "Reasoning…"

    try:
        for _ in range(settings.max_agent_iterations):
            yield ev.status(thinking)
            try:
                response = await provider.chat(messages, tools)
            except (LLMError, NotImplementedError) as e:
                message = f"LLM provider is unavailable: {e}"
                _save_unfinished(db, conversation, records, f"Chưa hoàn thành chẩn đoán: {message}")
                finished = True
                yield ev.error("LLM_UNAVAILABLE", message)
                yield ev.done()
                return
            except Exception as e:  # noqa: BLE001 — never leak a traceback into the stream
                log.exception("LLM call failed")
                message = f"LLM call failed: {type(e).__name__}"
                _save_unfinished(db, conversation, records, f"Chưa hoàn thành chẩn đoán: {message}")
                finished = True
                yield ev.error("LLM_UNAVAILABLE", message)
                yield ev.done()
                return

            if response.wants_tools:
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content=response.text or "",
                        tool_calls=response.tool_calls,
                    )
                )
                for call in response.tool_calls:
                    spec = tool_index.get(call.name)
                    yield ev.status(f"Reading {spec.label.lower() if spec else call.name}…")
                    yield AgentEvent(
                        type="tool_call",
                        data={"id": call.id, "tool": call.name, "input": call.input},
                    )
                    result = await asyncio.to_thread(run_tool, aws_session, call.name, call.input)
                    clean = sanitize(result.output)
                    summary = summarize_output(clean)
                    records.append(
                        ToolCallRecord(
                            tool=call.name,
                            input_json=json.dumps(call.input, default=str),
                            output_summary=summary,
                            status=result.status,
                            error=result.error,
                            duration_ms=result.duration_ms,
                        )
                    )
                    yield AgentEvent(
                        type="tool_result",
                        data={
                            "id": call.id,
                            "status": result.status,
                            "output_summary": summary,
                            "duration_ms": result.duration_ms,
                        },
                    )
                    messages.append(
                        LLMMessage(
                            role="tool",
                            tool_call_id=call.id,
                            tool_name=call.name,
                            content=json.dumps(clean, default=str),
                        )
                    )
                continue

            yield ev.status("Analyzing results…")
            answer = _parse_answer(response.text or "")
            if answer is None:
                if not retried_json:
                    retried_json = True
                    messages.append(LLMMessage(role="assistant", content=response.text or ""))
                    messages.append(LLMMessage(role="user", content=RETRY_JSON_PROMPT))
                    continue
                answer = _fallback_answer(response.text or "", tools)

            content = answer.summary
            assistant_msg = repo.add_message(
                db,
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=content,
                    answer_json=answer.model_dump_json(),
                ),
                records,
            )
            repo.touch_conversation(db, conversation)
            finished = True
            yield AgentEvent(
                type="answer",
                data={
                    "message_id": assistant_msg.id,
                    "content": content,
                    "answer": answer.model_dump(),
                },
            )
            yield ev.done()
            return

        steps = settings.max_agent_iterations
        _save_unfinished(
            db,
            conversation,
            records,
            f"Chưa hoàn thành chẩn đoán: dừng sau {steps} bước suy luận mà chưa có kết luận.",
        )
        finished = True
        yield ev.error(
            "MAX_ITERATIONS", f"Stopped after {steps} reasoning steps without a conclusion"
        )
        yield ev.done()
    finally:
        if not finished:
            try:
                _save_unfinished(db, conversation, records, STOPPED_NOTE)
            except Exception:  # noqa: BLE001 — do not mask the original exit reason
                log.exception("Could not store the unfinished turn")


def _save_unfinished(
    db: Session, conversation: Conversation, records: list[ToolCallRecord], note: str
) -> None:
    """Store an assistant message without answer for a turn that ended early."""
    repo.add_message(
        db,
        Message(conversation_id=conversation.id, role="assistant", content=note),
        records,
    )
    repo.touch_conversation(db, conversation)


# ---------------------------------------------------------------------------


def _history(db: Session, conversation_id: str, exclude_id: str) -> list[LLMMessage]:
    """Replay earlier turns so follow-up questions reuse what was already read."""
    out: list[LLMMessage] = []
    for m in repo.list_messages(db, conversation_id):
        if m.id == exclude_id:
            continue
        if m.role == "user":
            out.append(LLMMessage(role="user", content=m.content))
        else:
            calls = repo.list_tool_calls(db, m.id)
            read = "\n".join(f"- {c.tool}: {c.output_summary}" for c in calls)
            body = m.answer_json or m.content
            if read:
                body = f"[Data read earlier]\n{read}\n\n[Answer]\n{body}"
            out.append(LLMMessage(role="assistant", content=body))
    return out


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


def _fallback_answer(text: str, tools: list[ToolSpec]) -> DiagnosisAnswer:
    return DiagnosisAnswer(
        summary="Mô hình trả lời không đúng định dạng; dưới đây là nội dung thô.",
        cause=text[:1500] or "Không có nội dung.",
        evidence=[],
        fix_steps=[],
        unverified=[],
        confidence="low",
    )
