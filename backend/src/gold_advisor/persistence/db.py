from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from gold_advisor.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # prepare_threshold=None: Neon's pooled endpoint (PgBouncer) can't keep server-side prepared statements.
    # No pre-ping: it costs a full round trip per request (about 120 ms to Neon from Nepal).
    # Neon only drops connections when compute suspends after 5 idle minutes; recycling
    # connections after 4 minutes keeps every pooled connection younger than that.
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=False,
        pool_recycle=240,
        pool_size=5,
        max_overflow=5,
        connect_args={"prepare_threshold": None},
    )


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@lru_cache
def _read_session_factory() -> sessionmaker[Session]:
    # Autocommit: each read is one round trip, with no BEGIN/COMMIT around it.
    return sessionmaker(bind=get_engine().execution_options(isolation_level="AUTOCOMMIT"), expire_on_commit=False)


@contextmanager
def read_session_scope() -> Iterator[Session]:
    """For read-only requests (dashboard pages). Writes here commit immediately, statement by statement."""
    session = _read_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction per domain operation: commit on success, roll back on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
