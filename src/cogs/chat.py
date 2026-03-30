import discord
from discord.ext import commands
import logging
import asyncio
import os
import time
from collections import Counter
from services.db import db
from services.ai import ai_service
from services.autonomy import AutonomyEngine
from utils.humanizer import humanizer

logger = logging.getLogger(__name__)

class Chat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.autonomy_engine = AutonomyEngine(bot.user.id if bot.user else 0)
        self.context_isolation_mode = os.getenv("CONTEXT_ISOLATION_MODE", "smart").strip().lower()
        self.live_context_limit = int(os.getenv("LIVE_CONTEXT_LIMIT", "12"))
        # Pending cross-channel sends: user_id -> {target_channel, original_channel_id, expires_at}
        self._pending_channel_sends: dict = {}

    def _detect_cross_channel_intent(self, message):
        """
        Returns the first mentioned channel (not the current one) if the message
        expresses intent to send something to another channel.
        """
        if not getattr(message, "channel_mentions", None):
            return None
        content_lower = message.content.lower()
        intent_phrases = (
            "go to", "go in", "head to", "head in",
            "send to", "send in", "post in", "post to",
            "jump in", "jump to", "pop in", "drop in",
        )
        if not any(phrase in content_lower for phrase in intent_phrases):
            return None
        for ch in message.channel_mentions:
            if ch.id != message.channel.id:
                return ch
        return None

    async def _execute_cross_channel_send(self, message, target_channel):
        topic = message.content.strip()
        if not topic:
            await message.reply("nothing to go off lol, try again", mention_author=True)
            return
        try:
            # Fetch recent context from the target channel so the AI sounds like it belongs there.
            target_context = await db.get_recent_context(channel_id=target_channel.id, limit=8)
            ai_messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are about to post in #{target_channel.name} as a regular community member. "
                        f"Write a single natural Discord message on this topic: {topic}. "
                        "Do NOT explain what you're doing or acknowledge you're a bot. "
                        "Just write the message itself, as if you're genuinely posting in that channel."
                    ),
                }
            ]
            bot_user_id = self.bot.user.id if self.bot.user else None
            for msg in target_context:
                is_own = bool(msg.get("is_bot")) and msg.get("user_id") == bot_user_id
                role = "assistant" if is_own else "user"
                content = msg["content"]
                if not self._is_spammy_context(content):
                    ai_messages.append({"role": role, "content": content})

            async with target_channel.typing():
                generated = await ai_service.generate_response(ai_messages)

            if not generated or not generated.strip():
                await message.reply("ai blanked on me, try again", mention_author=True)
                return

            await target_channel.send(generated)
            await message.reply(f"posted in <#{target_channel.id}> 👌", mention_author=True)
            await db.log_message(
                user_id=self.bot.user.id,
                channel_id=target_channel.id,
                content=generated,
                author_name=self.bot.user.name,
                is_bot=True,
            )
        except discord.Forbidden:
            await message.reply(f"no perms to post in <#{target_channel.id}> 😬 someone give me access", mention_author=True)
        except Exception as exc:
            logger.exception("Cross-channel send failed: %s", exc)
            await message.reply("something went wrong, my bad", mention_author=True)

    def _resolve_context_user_id(self, message, reply_reason: str):
        mode = self.context_isolation_mode
        if mode == "channel_user":
            return message.author.id
        if mode == "channel":
            return None

        # Smart mode: direct interactions use per-user memory; proactive replies use shared channel memory.
        if mode == "smart":
            if reply_reason in {"direct_mention", "direct_reply"}:
                return message.author.id
            return None

        # Fallback for unexpected config values.
        return None

    def _is_spammy_context(self, content: str) -> bool:
        if not content:
            return True

        words = content.split()
        if len(content) > 450 and len(words) > 45:
            return True

        hashtags = [token.lower() for token in words if token.startswith("#") and len(token) > 1]
        if len(hashtags) >= 8:
            return True
        if hashtags:
            common_hashtag_count = Counter(hashtags).most_common(1)[0][1]
            if common_hashtag_count >= 3:
                return True

        return False

    async def _build_live_context(self, message):
        """
        Build fresh context from live Discord history, with explicit inclusion of replied-to message.
        """
        history_messages = []
        seen_ids = set()

        try:
            async for history_item in message.channel.history(limit=self.live_context_limit, oldest_first=False):
                if history_item.id in seen_ids:
                    continue
                seen_ids.add(history_item.id)
                history_messages.append(history_item)
        except Exception as exc:
            logger.warning("Failed to read live channel history: %s", exc)

        # Ensure the triggering message exists in context.
        if message.id not in seen_ids:
            history_messages.append(message)
            seen_ids.add(message.id)

        # Ensure replied-to message is included even if older than history limit.
        if message.reference and message.reference.message_id:
            try:
                referenced = message.reference.resolved
                if referenced is None:
                    referenced = await message.channel.fetch_message(message.reference.message_id)
                if referenced and referenced.id not in seen_ids:
                    history_messages.append(referenced)
                    seen_ids.add(referenced.id)
            except Exception as exc:
                logger.debug("Unable to include replied-to message in live context: %s", exc)

        history_messages.sort(key=lambda m: m.created_at)

        live_context = []
        for item in history_messages:
            content = (item.content or "").strip()
            if not content:
                continue
            live_context.append(
                {
                    "user_id": item.author.id,
                    "content": content,
                    "author_name": getattr(item.author, "display_name", None) or item.author.name,
                    "is_bot": bool(item.author.bot),
                    "created_at": item.created_at,
                }
            )

        return live_context

    def _build_mention_guidance(self, message, reply_reason: str) -> str:
        direct_response = reply_reason in {"direct_mention", "direct_reply"}
        guidance = [
            "Discord mention format: use <@USER_ID> when mentioning a user.",
            "Do not use plain @username mentions.",
            f"Triggering user: id={message.author.id}, mention=<@{message.author.id}>.",
        ]

        if direct_response:
            guidance.append("This is a direct interaction, start your reply by mentioning the triggering user exactly once.")
        else:
            guidance.append("This is a proactive jump-in, only mention someone if truly needed.")

        return " ".join(guidance)

    @commands.Cog.listener()
    async def on_ready(self):
        # Update bot ID in autonomy engine after login
        if self.bot.user:
            self.autonomy_engine.bot_id = self.bot.user.id

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author == self.bot.user:
                return

            if not message.content or not message.content.strip():
                return

            # 1. Log incoming message
            await db.log_message(
                user_id=message.author.id,
                channel_id=message.channel.id,
                content=message.content,
                author_name=message.author.name,
                is_bot=message.author.bot
            )

            # 2. Cross-channel send pipeline (takes priority over AI).
            if not message.author.bot:
                pending = self._pending_channel_sends.get(message.author.id)
                if pending:
                    if time.time() > pending["expires_at"]:
                        # Request timed out — silently discard.
                        del self._pending_channel_sends[message.author.id]
                    elif message.channel.id == pending["original_channel_id"]:
                        target_channel = pending["target_channel"]
                        del self._pending_channel_sends[message.author.id]
                        await self._execute_cross_channel_send(message, target_channel)
                        return

                if message.channel_mentions:
                    target = self._detect_cross_channel_intent(message)
                    if target:
                        self._pending_channel_sends[message.author.id] = {
                            "target_channel": target,
                            "original_channel_id": message.channel.id,
                            "expires_at": time.time() + 60,
                        }
                        await message.reply(
                            f"aight, what should I say in <#{target.id}>?",
                            mention_author=True,
                        )
                        return

            # 3. Get shared context to evaluate autonomy trigger.
            shared_context = await db.get_recent_context(channel_id=message.channel.id, limit=10)

            # 4. Autonomy check with reason.
            reply_reason = await self.autonomy_engine.get_reply_reason(message, shared_context)
            if reply_reason:
                direct_response = reply_reason in {"direct_mention", "direct_reply"}
                if direct_response:
                    # For direct interactions, prefer fresh live context over stale DB history.
                    response_context = await self._build_live_context(message)
                else:
                    context_user_id = self._resolve_context_user_id(message, reply_reason)
                    response_context = await db.get_recent_context(
                        channel_id=message.channel.id,
                        limit=10,
                        user_id=context_user_id,
                    )
                await self.handle_response(message, response_context, reply_reason)
        except Exception as e:
            logger.exception("Message pipeline failed for message %s: %s", message.id, e)

    async def handle_response(self, message, recent_context, reply_reason: str):
        logger.info("Decided to reply to message from %s", message.author.name)

        try:
            # 1. Simulate reading delay
            reading_delay = humanizer.calculate_reading_delay(message.content)
            await asyncio.sleep(reading_delay)

            # 2. Start typing indicator
            response_text = ""
            async with message.channel.typing():
                # 3. Simulate thinking delay
                thinking_delay = humanizer.calculate_thinking_delay()
                await asyncio.sleep(thinking_delay)

                # 4. Generate AI response
                messages_for_ai = [
                    {
                        "role": "system",
                        "content": self._build_mention_guidance(message, reply_reason),
                    }
                ]
                bot_user_id = self.bot.user.id if self.bot.user else None
                for msg in recent_context:
                    is_own_bot_message = bool(msg.get("is_bot")) and msg.get("user_id") == bot_user_id
                    role = "assistant" if is_own_bot_message else "user"
                    content = msg["content"]

                    if self._is_spammy_context(content):
                        continue

                    if role == "user":
                        user_id = msg.get("user_id")
                        if user_id is not None:
                            content = f"{msg['author_name']} (user_id={user_id}, mention=<@{user_id}>): {content}"
                        else:
                            content = f"{msg['author_name']}: {content}"
                    messages_for_ai.append({"role": role, "content": content})

                response_text = await ai_service.generate_response(messages_for_ai)

                if not response_text or response_text.strip() == "":
                    logger.warning("AI returned empty response.")
                    return

                # 5. Simulate typing delay based on response length
                typing_delay = humanizer.calculate_typing_delay(response_text)
                await asyncio.sleep(typing_delay)

            # 6. Send response after typing context closes so typing indicator does not linger.
            direct_response = reply_reason in {"direct_mention", "direct_reply"}
            if direct_response:
                await message.reply(response_text, mention_author=True)
            else:
                await message.channel.send(response_text)

            # 7. Log bot's response after typing indicator closes.
            await db.log_message(
                user_id=self.bot.user.id,
                channel_id=message.channel.id,
                content=response_text,
                author_name=self.bot.user.name,
                is_bot=True,
            )
        except Exception as e:
            logger.exception("Failed to handle response for message %s: %s", message.id, e)

async def setup(bot):
    await bot.add_cog(Chat(bot))
