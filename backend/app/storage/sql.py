"""SQLite implementation of the Store (default backend)."""

from sqlalchemy import update
from sqlmodel import Session, select

from app.storage.models import (
    Connection,
    Conversation,
    Message,
    Proposal,
    ToolCallRecord,
    utcnow,
)


class SqlStore:
    def __init__(self, session: Session) -> None:
        self.db = session

    # ---- connections ---------------------------------------------------------

    def create_connection(self, conn: Connection) -> Connection:
        self._save(conn)
        return conn

    def list_connections(self) -> list[Connection]:
        stmt = select(Connection).order_by(Connection.created_at.desc())
        return list(self.db.exec(stmt).all())

    def get_connection(self, conn_id: str) -> Connection | None:
        return self.db.get(Connection, conn_id)

    def save_connection(self, conn: Connection) -> None:
        self._save(conn)

    def delete_connection(self, conn: Connection) -> None:
        for conv in self.list_conversations(conn.id):
            self.delete_conversation(conv)
        self.db.delete(conn)
        self.db.commit()

    # ---- conversations -------------------------------------------------------

    def create_conversation(self, conv: Conversation) -> Conversation:
        self._save(conv)
        return conv

    def list_conversations(self, connection_id: str | None = None) -> list[Conversation]:
        stmt = select(Conversation)
        if connection_id:
            stmt = stmt.where(Conversation.connection_id == connection_id)
        return list(self.db.exec(stmt.order_by(Conversation.updated_at.desc())).all())

    def get_conversation(self, conv_id: str) -> Conversation | None:
        return self.db.get(Conversation, conv_id)

    def delete_conversation(self, conv: Conversation) -> None:
        for proposal in self.list_proposals(conversation_id=conv.id):
            self.db.delete(proposal)
        for msg in self.list_messages(conv.id):
            for tc in self.list_tool_calls(msg.id):
                self.db.delete(tc)
            self.db.delete(msg)
        self.db.delete(conv)
        self.db.commit()

    def touch_conversation(self, conv: Conversation, title: str | None = None) -> None:
        conv.updated_at = utcnow()
        if title and not conv.title:
            conv.title = title
        self.db.add(conv)
        self.db.commit()

    # ---- messages ------------------------------------------------------------

    def add_message(self, msg: Message, tool_calls: list[ToolCallRecord] | None = None) -> Message:
        self.db.add(msg)
        for i, tc in enumerate(tool_calls or []):
            tc.message_id = msg.id
            tc.seq = i
            self.db.add(tc)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def list_messages(self, conv_id: str) -> list[Message]:
        stmt = (
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
        )
        return list(self.db.exec(stmt).all())

    def list_tool_calls(self, message_id: str) -> list[ToolCallRecord]:
        stmt = (
            select(ToolCallRecord)
            .where(ToolCallRecord.message_id == message_id)
            .order_by(ToolCallRecord.seq)
        )
        return list(self.db.exec(stmt).all())

    # ---- remediation proposals -----------------------------------------------

    def create_proposal(self, proposal: Proposal) -> Proposal:
        self._save(proposal)
        return proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self.db.get(Proposal, proposal_id)

    def list_proposals(
        self, conversation_id: str | None = None, status: str | None = None
    ) -> list[Proposal]:
        stmt = select(Proposal)
        if conversation_id:
            stmt = stmt.where(Proposal.conversation_id == conversation_id)
        if status:
            stmt = stmt.where(Proposal.status == status)
        return list(self.db.exec(stmt.order_by(Proposal.created_at.desc())).all())

    def update_proposal(self, proposal: Proposal, expected_status: str | None = None) -> bool:
        proposal.updated_at = utcnow()
        if expected_status is None:
            self._save(proposal)
            return True
        values = proposal.model_dump(exclude={"id"})
        # The object may be attached with pending changes; a commit would write them without
        # the status condition. Detach it so only the conditional UPDATE below is applied.
        if proposal in self.db:
            self.db.expunge(proposal)
        result = self.db.exec(
            update(Proposal)
            .where(Proposal.id == proposal.id, Proposal.status == expected_status)
            .values(**values)
        )
        self.db.commit()
        if result.rowcount != 1:
            self.db.expire_all()
            return False
        return True

    # ---------------------------------------------------------------------------

    def _save(self, obj) -> None:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
