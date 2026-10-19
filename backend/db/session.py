from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from backend.core.config import settings

_URL = settings.DATABASE_URL
_IS_SQLITE = _URL.startswith("sqlite")
_IS_MEMORY_SQLITE = _IS_SQLITE and ":memory:" in _URL

# SQLite — used by the local sandbox and the test suite — rejects the pooled
# sizing arguments, so they are only applied to the server dialects that
# support them. An in-memory SQLite database additionally needs one shared
# connection or every session would see its own empty copy of the schema.
if _IS_MEMORY_SQLITE:
    engine = create_async_engine(
        _URL,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )
elif _IS_SQLITE:
    engine = create_async_engine(
        _URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
else:
    engine = create_async_engine(
        _URL,
        pool_size=20,
        max_overflow=40,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
