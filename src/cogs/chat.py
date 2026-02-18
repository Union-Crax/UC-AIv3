import discord
from discord.ext import commands
import logging
import asyncio
from services.db import db
from services.ai import ai_service
from services.autonomy import AutonomyEngine
from utils.humanizer import humanizer

logger = logging.getLogger(__name__)

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.autonomy_engine = AutonomyEngine(bot.user.id if bot.user else 0)

    @commands.Cog.listener()
    async def on_ready(self):
        # Update bot ID in autonomy engine after login
        if self.bot.user:
            self.autonomy_engine.bot_id = self.bot.user.id

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        # 1. Log incoming message
        try:
            await db.log_message(
                user_id=message.author.id,
                channel_id=message.channel.id,
                content=message.content,
                author_name=message.author.name,
                is_bot=message.author.bot
            )
        except Exception as e:
            logger.error(f"Failed to log message: {e}")

        # 2. Get recent context
        try:
            recent_context = await db.get_recent_context(message.channel.id, limit=10)
        except Exception as e:
            logger.error(f"Failed to fetch context: {e}")
            recent_context = []

        # 3. Autonomy check
        should_reply = await self.autonomy_engine.should_reply(message, recent_context)

        if should_reply:
            await self.handle_response(message, recent_context)

    async def handle_response(self, message, recent_context):
        logger.info(f"Decided to reply to message from {message.author.name}")

        # 1. Simulate reading delay
        reading_delay = humanizer.calculate_reading_delay(message.content)
        await asyncio.sleep(reading_delay)

        # 2. Start typing indicator
        async with message.channel.typing():
            # 3. Simulate thinking delay
            thinking_delay = humanizer.calculate_thinking_delay()
            await asyncio.sleep(thinking_delay)

            # 4. Generate AI response
            # Format context for AI
            messages_for_ai = []
            for msg in recent_context:
                role = "assistant" if msg['is_bot'] else "user"
                # Add author name to user messages for better context understanding
                content = msg['content']
                if role == "user":
                    content = f"{msg['author_name']}: {content}"
                messages_for_ai.append({"role": role, "content": content})

            # Add current message if not already in context (it should be, but just in case of race condition or DB delay)
            # Actually, we logged it, so it should be in recent_context if we fetched after logging.
            # But let's verify. Yes, we fetch after log.

            response_text = await ai_service.generate_response(messages_for_ai)

            if not response_text or response_text.strip() == "":
                logger.warning("AI returned empty response.")
                return

            # 5. Simulate typing delay based on response length
            typing_delay = humanizer.calculate_typing_delay(response_text)
            # We are already inside async with typing(), so it shows typing status.
            # But we need to wait *while* typing.
            # However, AI generation takes time too.
            # We can subtract generation time from typing delay?
            # Or just add typing delay ON TOP of generation time to be safe?
            # Let's just wait the typing delay.
            await asyncio.sleep(typing_delay)

            # 6. Send response
            sent_message = await message.channel.send(response_text)

            # 7. Log bot's response
            try:
                await db.log_message(
                    user_id=self.bot.user.id,
                    channel_id=message.channel.id,
                    content=response_text,
                    author_name=self.bot.user.name,
                    is_bot=True
                )
            except Exception as e:
                logger.error(f"Failed to log bot response: {e}")

async def setup(bot):
    await bot.add_cog(Chat(bot))
