"""Storage interface used by the routers and the agent loop.

Two implementations: ``SqlStore`` (SQLite via SQLModel, default) and ``DynamoStore``
(DynamoDB, the target storage of docs/SYSTEM_OVERVIEW.md §7). Pick one with
STORAGE_BACKEND; ``app.storage.store.get_store`` builds the right one per request.
"""

from typing import Protocol

from app.storage.models import Connection, Conversation, Message, ToolCallRecord


class Store(Protocol):
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
