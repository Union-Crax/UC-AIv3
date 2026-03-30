import asyncpg
import os
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool = None
        self.db_url = None

    async def connect(self):
        self.db_url = os.getenv("DATABASE_URL")
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is not set.")

        try:
            self.pool = await asyncpg.create_pool(
                dsn=self.db_url,
                min_size=1,
                max_size=10,
                command_timeout=30,
            )
            await self.health_check()
            logger.info("Connected to the database.")
            await self.create_tables()
        except Exception as e:
            logger.error(f"Failed to connect to the database: {e}")
            raise

    async def health_check(self):
        pool = self._get_pool_or_raise()
        async with pool.acquire() as connection:
            await connection.execute("SELECT 1")

    def _get_pool_or_raise(self):
        if not self.pool:
            raise RuntimeError("Database pool is not initialized.")
        return self.pool

    async def create_tables(self):
        query = """
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            content TEXT NOT NULL,
            author_name TEXT NOT NULL,
            is_bot BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_messages_channel_created
        ON messages (channel_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_messages_created_at
        ON messages (created_at DESC);
        """
        pool = self._get_pool_or_raise()
        async with pool.acquire() as connection:
            await connection.execute(query)

    async def log_message(self, user_id: int, channel_id: int, content: str, author_name: str, is_bot: bool = False):
        query = """
        INSERT INTO messages (user_id, channel_id, content, author_name, is_bot)
        VALUES ($1, $2, $3, $4, $5)
        """
        pool = self._get_pool_or_raise()
        async with pool.acquire() as connection:
            await connection.execute(query, user_id, channel_id, content, author_name, is_bot)

    async def get_recent_context(self, channel_id: int, limit: int = 20, user_id: int = None) -> List[Dict]:
        if user_id is None:
            query = """
            SELECT user_id, content, author_name, is_bot, created_at
            FROM messages
            WHERE channel_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """
            args = (channel_id, limit)
        else:
            # In channel_user mode, keep user-specific history plus bot messages in this channel.
            query = """
            SELECT user_id, content, author_name, is_bot, created_at
            FROM messages
            WHERE channel_id = $1
            AND (user_id = $2 OR is_bot = TRUE)
            ORDER BY created_at DESC
            LIMIT $3
            """
            args = (channel_id, user_id, limit)

        pool = self._get_pool_or_raise()
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *args)
            # Return reversed so it's chronological
            return [dict(row) for row in reversed(rows)]

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("Database connection closed.")

db = Database()
