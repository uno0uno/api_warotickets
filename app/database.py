import asyncpg
from contextlib import asynccontextmanager
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class DatabasePool:
    _pool = None

    @classmethod
    async def create_pool(cls):
        if cls._pool is None:
            try:
                cls._pool = await asyncpg.create_pool(
                    **settings.db_connection_params,
                    min_size=5,
                    max_size=30,
                    max_queries=50000,
                    max_inactive_connection_lifetime=300,
                    command_timeout=60,
                    timeout=30
                )
                logger.info(f"Database pool created: {settings.db_name}@{settings.db_host}")
            except Exception as e:
                logger.error(f"Failed to create database pool: {e}")
                raise
        return cls._pool

    @classmethod
    async def close_pool(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
            logger.info("Database pool closed")

@asynccontextmanager
async def get_db_connection(use_transaction: bool = True):
    """
    Get database connection from pool.

    Args:
        use_transaction: If True, wraps operations in a transaction.
                        Set to False for read-only operations.

    Usage:
    async with get_db_connection() as conn:
        result = await conn.fetchrow("SELECT * FROM table WHERE id = $1", id)

    Read-only usage:
    async with get_db_connection(use_transaction=False) as conn:
        result = await conn.fetchrow("SELECT * FROM table WHERE id = $1", id)
    """
    pool = await DatabasePool.create_pool()
    async with pool.acquire() as connection:
        if use_transaction:
            async with connection.transaction():
                yield connection
        else:
            yield connection
