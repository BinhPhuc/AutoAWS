"""SQLite implementation of the Store (default backend)."""

from sqlalchemy import update
from sqlmodel import Session, select

from app.storage.models import (
    Connection,
    Conversation,
    Job,
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

    def list_connections(self, user_id: str | None = None) -> list[Connection]:
        stmt = select(Connection)
        if user_id is not None:
            stmt = stmt.where(Connection.user_id == user_id)
        return list(self.db.exec(stmt.order_by(Connection.created_at.desc())).all())

    def get_connection(self, conn_id: str) -> Connection | None:
        return self.db.get(Connection, conn_id)

    def find_connection_by_external_id(self, external_id: str) -> Connection | None:
        stmt = select(Connection).where(Connection.external_id == external_id)
        return self.db.exec(stmt).first()

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

    def list_conversations(
        self, connection_id: str | None = None, user_id: str | None = None
    ) -> list[Conversation]:
        stmt = select(Conversation)
        if connection_id:
            stmt = stmt.where(Conversation.connection_id == connection_id)
        if user_id is not None:
            stmt = stmt.where(Conversation.user_id == user_id)
        return list(self.db.exec(stmt.order_by(Conversation.updated_at.desc())).all())

    def get_conversation(self, conv_id: str) -> Conversation | None:
        return self.db.get(Conversation, conv_id)

    def delete_conversation(self, conv: Conversation) -> None:
        for job in self.list_jobs(conv.id):
            self.db.delete(job)
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
        self,
        conversation_id: str | None = None,
        status: str | None = None,
        user_id: str | None = None,
    ) -> list[Proposal]:
        stmt = select(Proposal)
        if user_id is not None:
            stmt = stmt.where(Proposal.user_id == user_id)
        if conversation_id:
            stmt = stmt.where(Proposal.conversation_id == conversation_id)
        if status:
            stmt = stmt.where(Proposal.status == status)
        return list(self.db.exec(stmt.order_by(Proposal.created_at.desc())).all())

    def update_proposal(self, proposal: Proposal, expected_status: str | None = None) -> bool:
        proposal.updated_at = utcnow()
        values = proposal.model_dump(exclude={"id", "task_token"})
        # The object may be attached with pending changes; a commit would write them without
        # the status condition. Detach it so only the conditional UPDATE below is applied.
        if proposal in self.db:
            self.db.expunge(proposal)
        stmt = update(Proposal).where(Proposal.id == proposal.id)
        if expected_status is not None:
            stmt = stmt.where(Proposal.status == expected_status)
        result = self.db.exec(stmt.values(**values))
        self.db.commit()
        if result.rowcount != 1:
            self.db.expire_all()
            return False
        return True

    def set_proposal_token(self, proposal_id: str, task_token: str | None) -> None:
        self.db.exec(
            update(Proposal).where(Proposal.id == proposal_id).values(task_token=task_token)
        )
        self.db.commit()
        self.db.expire_all()

    # ---- jobs ----------------------------------------------------------------

    def create_job(self, job: Job) -> Job:
        self._save(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        job = self.db.get(Job, job_id)
        if job is not None:
            self.db.refresh(job)  # another session (the worker) may have written it
        return job

    def list_jobs(self, conversation_id: str) -> list[Job]:
        stmt = select(Job).where(Job.conversation_id == conversation_id)
        return list(self.db.exec(stmt.order_by(Job.created_at.desc())).all())

    def update_job(self, job_id: str, **fields) -> None:
        fields["updated_at"] = utcnow()
        self.db.exec(update(Job).where(Job.id == job_id).values(**fields))
        self.db.commit()
        self.db.expire_all()

    # ---------------------------------------------------------------------------

    def _save(self, obj) -> None:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
