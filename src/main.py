import os
import discord
import logging
from discord.ext import commands
from dotenv import load_dotenv
from services.db import db

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

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
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN is not set in .env file.")
        return

    bot = MyBot()
    bot.run(token)

if __name__ == "__main__":
    main()
