import os
import sys
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv

# Ensure local absolute imports work when running either `python -m src.main` or `python src/main.py`.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from services.db import db

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

REQUIRED_ENV_VARS = ["DISCORD_TOKEN", "OPENROUTER_API_KEY", "DATABASE_URL"]


def get_missing_required_env_vars():
    missing = []
    for key in REQUIRED_ENV_VARS:
        value = os.getenv(key)
        if value is None or value.strip() == "":
            missing.append(key)
    return missing

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await db.connect()
        await self.load_extension("cogs.chat")
        logger.info("Bot setup complete.")

    async def close(self):
        await db.close()
        await super().close()

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')

def main():
    missing = get_missing_required_env_vars()
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        raise SystemExit(1)

    token = os.getenv("DISCORD_TOKEN")

    bot = MyBot()
    try:
        bot.run(token)
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")

if __name__ == "__main__":
    main()
