"""Thin CRUD helpers so routers and the agent loop never touch the ORM directly."""

from sqlmodel import Session, select

from app.storage.models import Connection, Conversation, Message, ToolCallRecord, utcnow

# ---- connections -------------------------------------------------------------


def create_connection(db: Session, conn: Connection) -> Connection:
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def list_connections(db: Session) -> list[Connection]:
    return list(db.exec(select(Connection).order_by(Connection.created_at.desc())).all())


def get_connection(db: Session, conn_id: str) -> Connection | None:
    return db.get(Connection, conn_id)


def save(db: Session, obj) -> None:
    db.add(obj)
    db.commit()
    db.refresh(obj)


def delete_connection(db: Session, conn: Connection) -> None:
    for conv in list_conversations(db, conn.id):
        delete_conversation(db, conv)
    db.delete(conn)
    db.commit()


# ---- conversations -----------------------------------------------------------


def create_conversation(db: Session, conv: Conversation) -> Conversation:
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def list_conversations(db: Session, connection_id: str | None = None) -> list[Conversation]:
    stmt = select(Conversation)
    if connection_id:
        stmt = stmt.where(Conversation.connection_id == connection_id)
    return list(db.exec(stmt.order_by(Conversation.updated_at.desc())).all())


def get_conversation(db: Session, conv_id: str) -> Conversation | None:
    return db.get(Conversation, conv_id)


def delete_conversation(db: Session, conv: Conversation) -> None:
    for msg in list_messages(db, conv.id):
        for tc in list_tool_calls(db, msg.id):
            db.delete(tc)
        db.delete(msg)
    db.delete(conv)
    db.commit()


def touch_conversation(db: Session, conv: Conversation, title: str | None = None) -> None:
    conv.updated_at = utcnow()
    if title and not conv.title:
        conv.title = title
    db.add(conv)
    db.commit()


# ---- messages ----------------------------------------------------------------


def add_message(
    db: Session, msg: Message, tool_calls: list[ToolCallRecord] | None = None
) -> Message:
    db.add(msg)
    for i, tc in enumerate(tool_calls or []):
        tc.message_id = msg.id
        tc.seq = i
        db.add(tc)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages(db: Session, conv_id: str) -> list[Message]:
    stmt = select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
    return list(db.exec(stmt).all())


def list_tool_calls(db: Session, message_id: str) -> list[ToolCallRecord]:
    stmt = (
        select(ToolCallRecord)
        .where(ToolCallRecord.message_id == message_id)
        .order_by(ToolCallRecord.seq)
    )
    return list(db.exec(stmt).all())
