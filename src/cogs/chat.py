import discord
from discord.ext import commands
import logging
import asyncio
import os
import random
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
        # Runtime ignore list: user/bot IDs this bot will not respond to until cleared.
        self._ignored_for_session: set = set()

    async def _resolve_command_targets(self, message) -> list:
        """Return IDs of target users from @mentions, or by name-matching recent history."""
        bot_id = self.bot.user.id if self.bot.user else 0
        targets = [u.id for u in message.mentions if u.id != bot_id]
        if targets:
            return targets
        # No @mentions — scan recent history for bots whose name appears in the message.
        content_lower = message.content.lower()
        try:
            async for item in message.channel.history(limit=30):
                if item.author.bot and item.author.id != bot_id:
                    name = (getattr(item.author, "display_name", None) or item.author.name).lower()
                    if name in content_lower or any(part in content_lower for part in name.split() if len(part) > 2):
                        if item.author.id not in targets:
                            targets.append(item.author.id)
                        break
        except Exception:
            pass
        return targets

    async def _handle_control_command(self, message) -> bool:
        """
        Detects runtime commands like "stop replying to veebot" or "you can talk to them again".
        Returns True if the message was a control command and has been handled.
        """
        content_lower = message.content.lower()
        # Quick pre-filter to avoid unnecessary AI calls.
        has_stop_signal = any(w in content_lower for w in ("stop", "don't", "dont", "ignore", "no more", "never", "not reply", "no reply"))
        has_resume_signal = any(w in content_lower for w in ("unignore", "un-ignore", "resume", "can reply", "reply to them", "talk to them", "respond to"))
        if not has_stop_signal and not has_resume_signal:
            return False

        if has_stop_signal:
            is_stop = await ai_service.classify(
                f'Message: "{message.content}"\n'
                "Is the user telling the bot to completely stop replying to or engaging with a specific person?"
            )
            if is_stop:
                targets = await self._resolve_command_targets(message)
                if not targets:
                    return False
                for uid in targets:
                    self._ignored_for_session.add(uid)
                names = ", ".join(f"<@{uid}>" for uid in targets)
                async with message.channel.typing():
                    await asyncio.sleep(humanizer.calculate_thinking_delay())
                await message.reply(f"got it, not engaging with {names} anymore", mention_author=False)
                logger.info("Session ignore added: %s", targets)
                return True

        if has_resume_signal:
            is_resume = await ai_service.classify(
                f'Message: "{message.content}"\n'
                "Is the user telling the bot it can resume replying to someone they previously asked it to ignore?"
            )
            if is_resume:
                targets = await self._resolve_command_targets(message)
                for uid in targets:
                    self._ignored_for_session.discard(uid)
                if targets:
                    names = ", ".join(f"<@{uid}>" for uid in targets)
                    await message.reply(f"aight, back to normal with {names}", mention_author=False)
                logger.info("Session ignore removed: %s", targets)
                return True

        return False

    async def _is_conversation_ending(self, text: str) -> bool:
        """Return True if the text signals the sender is ending the conversation."""
        low = text.lower()
        # Quick pre-filter to avoid unnecessary classify calls.
        hints = (
            "bye", "peace", "later", "goodbye", "goodnight", "good night", "gtg",
            "gotta go", "heading out", "signing off", "enough", "done", "cya",
            "see ya", "see you later", "take care", "leaving", "log off", "out for",
            "catch you", "nirvana", "sleep", "done talking", "done for now",
        )
        if not any(h in low for h in hints):
            return False
        return await ai_service.classify(
            f'Message: "{text}"\n'
            "Is this message saying goodbye, wrapping up the conversation, or indicating the person is leaving or done talking?"
        )

    async def _detect_cross_channel_intent(self, message):
        """
        Returns the first mentioned channel (not the current one) if the AI
        decides the message is a request to go post something there.
        """
        if not getattr(message, "channel_mentions", None):
            return None
        for ch in message.channel_mentions:
            if ch.id == message.channel.id:
                continue
            question = (
                f'The user sent this message: "{message.content}"\n'
                f'Are they asking a Discord bot to go post something in the channel #{ch.name}?'
            )
            if await ai_service.classify(question):
                return ch
        return None

    async def _execute_cross_channel_send(self, message, target_channel):
        try:
            # Sometimes acknowledge in the original channel first (like a real person), sometimes say nothing.
            if random.random() < 0.6:
                ack_messages = [
                    {
                        "role": "system",
                        "content": (
                            "Write a very short casual acknowledgment (max 6 words) that you're heading to another channel. "
                            "Examples: 'Sure thing!', 'on it', 'heading there', 'say less'. "
                            "No emojis required, no mentions, just the words."
                        ),
                    }
                ]
                async with message.channel.typing():
                    await asyncio.sleep(humanizer.calculate_thinking_delay())
                    ack = await ai_service.generate_response(ack_messages)
                if ack and ack.strip():
                    await asyncio.sleep(humanizer.calculate_typing_delay(ack))
                    await message.reply(ack.strip(), mention_author=False)

            # Small natural pause before appearing in the other channel.
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Pull recent target-channel context so the AI fits the vibe there.
            target_context = await db.get_recent_context(channel_id=target_channel.id, limit=8)
            bot_user_id = self.bot.user.id if self.bot.user else None
            ai_messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are joining #{target_channel.name} as a regular community member. "
                        f"<@{message.author.id}> asked you to come here. "
                        "Write one natural Discord message to kick off the conversation — "
                        f"start by mentioning <@{message.author.id}> exactly once, then say something fitting for this channel. "
                        "Do not explain that you are a bot or that you were asked to come here."
                    ),
                }
            ]
            for msg in target_context:
                is_own = bool(msg.get("is_bot")) and msg.get("user_id") == bot_user_id
                role = "assistant" if is_own else "user"
                content = msg["content"]
                if not self._is_spammy_context(content):
                    ai_messages.append({"role": role, "content": content})

            async with target_channel.typing():
                await asyncio.sleep(humanizer.calculate_thinking_delay())
                generated = await ai_service.generate_response(ai_messages)
                if generated and generated.strip():
                    await asyncio.sleep(humanizer.calculate_typing_delay(generated))

            if not generated or not generated.strip():
                return

            await target_channel.send(generated)
            await db.log_message(
                user_id=self.bot.user.id,
                channel_id=target_channel.id,
                content=generated,
                author_name=self.bot.user.name,
                is_bot=True,
            )
        except discord.Forbidden:
            await message.reply(f"no perms to post in <#{target_channel.id}> 😬 someone give me access", mention_author=False)
        except Exception as exc:
            logger.exception("Cross-channel send failed: %s", exc)
            await message.reply("something went wrong, my bad", mention_author=False)

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
            guidance.append("This is a direct interaction. Do NOT start your reply with a mention — the Discord reply thread already shows who you're talking to. Only mention someone mid-reply if you genuinely need to address them by name.")
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

            # 2. Skip any response if this sender is on the session ignore list.
            if message.author.id in self._ignored_for_session:
                return

            # 3. Cross-channel send pipeline (takes priority over AI).
            if not message.author.bot and message.channel_mentions:
                target = await self._detect_cross_channel_intent(message)
                if target:
                    await self._execute_cross_channel_send(message, target)
                    return

            # 4. Get shared context to evaluate autonomy trigger.
            shared_context = await db.get_recent_context(channel_id=message.channel.id, limit=10)

            # 5. Autonomy check with reason.
            reply_reason = await self.autonomy_engine.get_reply_reason(message, shared_context)
            if reply_reason:
                direct_response = reply_reason in {"direct_mention", "direct_reply"}

                # 5a. If a friendly bot is saying goodbye, close the convo and let them have the last word.
                if message.author.bot and await self._is_conversation_ending(message.content):
                    self.autonomy_engine.close_convo(message.channel.id)
                    logger.info("Friendly bot goodbye detected; closing convo in channel %s.", message.channel.id)
                    return

                # 6. Check for runtime control commands on direct interactions, before generating a reply.
                if direct_response and not message.author.bot:
                    handled = await self._handle_control_command(message)
                    if handled:
                        return

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
                await message.reply(response_text, mention_author=False)
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

            # 8. If the bot's own reply sounds like a goodbye and the conversation partner is
            #    a friendly bot, seal the channel so the other bot's follow-up goes unanswered.
            if message.author.bot and await self._is_conversation_ending(response_text):
                self.autonomy_engine.close_convo(message.channel.id)
                logger.info("Bot sent a goodbye; closing convo in channel %s.", message.channel.id)
        except Exception as e:
            logger.exception("Failed to handle response for message %s: %s", message.id, e)

async def setup(bot):
    await bot.add_cog(Chat(bot))
