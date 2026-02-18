import asyncpg
import os
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool = None
        self.db_url = os.getenv("DATABASE_URL")

    async def connect(self):
        if not self.db_url:
            logger.error("DATABASE_URL is not set.")
            return

        try:
            self.pool = await asyncpg.create_pool(self.db_url)
            logger.info("Connected to the database.")
            await self.create_tables()
        except Exception as e:
            logger.error(f"Failed to connect to the database: {e}")
            raise

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
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query)

    async def log_message(self, user_id: int, channel_id: int, content: str, author_name: str, is_bot: bool = False):
        query = """
        INSERT INTO messages (user_id, channel_id, content, author_name, is_bot)
        VALUES ($1, $2, $3, $4, $5)
        """
        async with self.pool.acquire() as connection:
            await connection.execute(query, user_id, channel_id, content, author_name, is_bot)

    async def get_recent_context(self, channel_id: int, limit: int = 20) -> List[Dict]:
        query = """
        SELECT user_id, content, author_name, is_bot, created_at
        FROM messages
        WHERE channel_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(query, channel_id, limit)
            # Return reversed so it's chronological
            return [dict(row) for row in reversed(rows)]

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("Database connection closed.")

db = Database()
