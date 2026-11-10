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
    def __init__(self, session: Session, user_id: str = "local-dev") -> None:
        self.db = session
        self.user_id = user_id

    # ---- connections ---------------------------------------------------------

    def create_connection(self, conn: Connection) -> Connection:
        conn.user_id = self.user_id
        self._save(conn)
        return conn

    def list_connections(self) -> list[Connection]:
        stmt = (
            select(Connection)
            .where(Connection.user_id == self.user_id)
            .order_by(Connection.created_at.desc())
        )
        return list(self.db.exec(stmt).all())

    def get_connection(self, conn_id: str) -> Connection | None:
        return self.db.exec(
            select(Connection).where(Connection.id == conn_id, Connection.user_id == self.user_id)
        ).first()

    def save_connection(self, conn: Connection) -> None:
        self._owned(conn)
        self._save(conn)

    def delete_connection(self, conn: Connection) -> None:
        self._owned(conn)
        for conv in self.list_conversations(conn.id):
            self.delete_conversation(conv)
        self.db.delete(conn)
        self.db.commit()

    # ---- conversations -------------------------------------------------------

    def create_conversation(self, conv: Conversation) -> Conversation:
        conv.user_id = self.user_id
        self._save(conv)
        return conv

    def list_conversations(self, connection_id: str | None = None) -> list[Conversation]:
        stmt = select(Conversation).where(Conversation.user_id == self.user_id)
        if connection_id:
            stmt = stmt.where(Conversation.connection_id == connection_id)
        return list(self.db.exec(stmt.order_by(Conversation.updated_at.desc())).all())

    def get_conversation(self, conv_id: str) -> Conversation | None:
        return self.db.exec(
            select(Conversation).where(
                Conversation.id == conv_id, Conversation.user_id == self.user_id
            )
        ).first()

    def delete_conversation(self, conv: Conversation) -> None:
        self._owned(conv)
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
        self._owned(conv)
        conv.updated_at = utcnow()
        if title and not conv.title:
            conv.title = title
        self.db.add(conv)
        self.db.commit()

    # ---- messages ------------------------------------------------------------

    def add_message(self, msg: Message, tool_calls: list[ToolCallRecord] | None = None) -> Message:
        msg.user_id = self.user_id
        self.db.add(msg)
        for i, tc in enumerate(tool_calls or []):
            tc.user_id = self.user_id
            tc.message_id = msg.id
            tc.seq = i
            self.db.add(tc)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def list_messages(self, conv_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.user_id == self.user_id)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
        )
        return list(self.db.exec(stmt).all())

    def list_tool_calls(self, message_id: str) -> list[ToolCallRecord]:
        stmt = (
            select(ToolCallRecord)
            .where(ToolCallRecord.user_id == self.user_id)
            .where(ToolCallRecord.message_id == message_id)
            .order_by(ToolCallRecord.seq)
        )
        return list(self.db.exec(stmt).all())

    # ---- remediation proposals -----------------------------------------------

    def create_proposal(self, proposal: Proposal) -> Proposal:
        proposal.user_id = self.user_id
        self._save(proposal)
        return proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self.db.exec(
            select(Proposal).where(Proposal.id == proposal_id, Proposal.user_id == self.user_id)
        ).first()

    def list_proposals(
        self, conversation_id: str | None = None, status: str | None = None
    ) -> list[Proposal]:
        stmt = select(Proposal).where(Proposal.user_id == self.user_id)
        if conversation_id:
            stmt = stmt.where(Proposal.conversation_id == conversation_id)
        if status:
            stmt = stmt.where(Proposal.status == status)
        return list(self.db.exec(stmt.order_by(Proposal.created_at.desc())).all())

    def update_proposal(self, proposal: Proposal, expected_status: str | None = None) -> bool:
        self._owned(proposal)
        proposal.updated_at = utcnow()
        values = proposal.model_dump(exclude={"id", "task_token"})
        # The object may be attached with pending changes; a commit would write them without
        # the status condition. Detach it so only the conditional UPDATE below is applied.
        if proposal in self.db:
            self.db.expunge(proposal)
        stmt = update(Proposal).where(Proposal.id == proposal.id, Proposal.user_id == self.user_id)
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
            update(Proposal)
            .where(Proposal.id == proposal_id, Proposal.user_id == self.user_id)
            .values(task_token=task_token)
        )
        self.db.commit()
        self.db.expire_all()

    # ---- jobs ----------------------------------------------------------------

    def create_job(self, job: Job) -> Job:
        job.user_id = self.user_id
        self._save(job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        job = self.db.exec(select(Job).where(Job.id == job_id, Job.user_id == self.user_id)).first()
        if job is not None:
            self.db.refresh(job)  # another session (the worker) may have written it
        return job

    def list_jobs(self, conversation_id: str) -> list[Job]:
        stmt = (
            select(Job)
            .where(Job.user_id == self.user_id)
            .where(Job.conversation_id == conversation_id)
        )
        return list(self.db.exec(stmt.order_by(Job.created_at.desc())).all())

    def update_job(self, job_id: str, **fields) -> None:
        if "user_id" in fields or "id" in fields or "conversation_id" in fields:
            raise ValueError("Cannot change job ownership")
        fields["updated_at"] = utcnow()
        self.db.exec(
            update(Job).where(Job.id == job_id, Job.user_id == self.user_id).values(**fields)
        )
        self.db.commit()
        self.db.expire_all()

    # ---------------------------------------------------------------------------

    def _owned(self, obj) -> None:
        if obj.user_id != self.user_id:
            raise ValueError("Owner mismatch")

    def _save(self, obj) -> None:
        self._owned(obj)
        # Check persisted ownership without autoflushing an attached, modified object.
        model = type(obj)
        with self.db.no_autoflush:
            row = self.db.exec(select(model.id, model.user_id).where(model.id == obj.id)).first()
        if row is not None and row[1] != self.user_id:
            raise ValueError("Owner mismatch")
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
