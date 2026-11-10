from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(f"sqlite:///{settings.db_path}", connect_args={"check_same_thread": False})


def init_db() -> None:
    from app.storage import models  # noqa: F401  (register tables)

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    if any(c.endswith(".user_id") for c in add_missing_columns(engine)):
        backfill_owner(engine)


def backfill_owner(engine: Engine) -> None:
    """Rows from before sign-in existed belong to the local user."""
    from app.storage.models import LOCAL_USER_ID

    existing = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name in existing and "user_id" in table.columns:
                conn.execute(
                    text(f'UPDATE "{table.name}" SET user_id = :u WHERE user_id IS NULL'),
                    {"u": LOCAL_USER_ID},
                )


def add_missing_columns(engine: Engine) -> list[str]:
    """``create_all`` never alters existing tables: add columns that were introduced after
    a (dev) database was created. New columns are nullable. Returns what was added."""
    existing_tables = set(inspect(engine).get_table_names())
    added = []
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspect(conn).get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                ddl = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))
                added.append(f"{table.name}.{column.name}")
    return added


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
