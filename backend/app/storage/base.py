"""Storage interface used by the routers and the agent loop.

Two implementations: ``SqlStore`` (SQLite via SQLModel, explicit local option) and ``DynamoStore``
(DynamoDB, the target storage of docs/SYSTEM_OVERVIEW.md §7). Pick one with
STORAGE_BACKEND; ``app.storage.store.get_store`` builds the right one per request.
"""

from typing import Protocol

from app.storage.models import Connection, Conversation, Job, Message, Proposal, ToolCallRecord


class Store(Protocol):
    user_id: str

    # ---- connections ---------------------------------------------------------
    def create_connection(self, conn: Connection) -> Connection: ...

    def list_connections(self) -> list[Connection]:
        """Newest first."""
        ...

    def get_connection(self, conn_id: str) -> Connection | None: ...

    def save_connection(self, conn: Connection) -> None: ...

    def delete_connection(self, conn: Connection) -> None:
        """Also deletes the connection's conversations, messages and tool calls."""
        ...

    # ---- conversations -------------------------------------------------------
    def create_conversation(self, conv: Conversation) -> Conversation: ...

    def list_conversations(self, connection_id: str | None = None) -> list[Conversation]:
        """Most recently updated first."""
        ...

    def get_conversation(self, conv_id: str) -> Conversation | None: ...

    def delete_conversation(self, conv: Conversation) -> None: ...

    def touch_conversation(self, conv: Conversation, title: str | None = None) -> None:
        """Bump ``updated_at``; set the title only if it is still empty."""
        ...

    # ---- messages ------------------------------------------------------------
    def add_message(
        self, msg: Message, tool_calls: list[ToolCallRecord] | None = None
    ) -> Message: ...

    def list_messages(self, conv_id: str) -> list[Message]:
        """Oldest first."""
        ...

    def list_tool_calls(self, message_id: str) -> list[ToolCallRecord]:
        """In the order they ran."""
        ...

    # ---- remediation proposals -----------------------------------------------
    def create_proposal(self, proposal: Proposal) -> Proposal: ...

    def get_proposal(self, proposal_id: str) -> Proposal | None: ...

    def list_proposals(
        self, conversation_id: str | None = None, status: str | None = None
    ) -> list[Proposal]:
        """Newest first."""
        ...

    def update_proposal(self, proposal: Proposal, expected_status: str | None = None) -> bool:
        """Save; with ``expected_status`` only if the stored status still equals it
        (compare-and-set, so a proposal is never executed twice). True if saved.
        Never writes ``task_token`` (see ``set_proposal_token``)."""
        ...

    def set_proposal_token(self, proposal_id: str, task_token: str | None) -> None:
        """Store only the Step Functions task token (written concurrently with decisions)."""
        ...

    # ---- jobs (background diagnosis turns) -------------------------------------
    def create_job(self, job: Job) -> Job: ...

    def get_job(self, job_id: str) -> Job | None: ...

    def list_jobs(self, conversation_id: str) -> list[Job]:
        """Newest first."""
        ...

    def update_job(self, job_id: str, **fields) -> None:
        """Set only these fields (the worker writes events while the API may set
        ``cancel_requested``; neither overwrites the other). Bumps ``updated_at``."""
        ...
