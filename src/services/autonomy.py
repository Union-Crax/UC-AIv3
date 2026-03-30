import random
import logging
import os
from typing import List, Dict

logger = logging.getLogger(__name__)

class AutonomyEngine:
    def __init__(self, bot_id: int):
        self.bot_id = bot_id
        self.mode = os.getenv("AUTONOMY_MODE", "balanced").strip().lower()
        self.continue_reply_chance = self._clamp_probability(os.getenv("CONTINUE_REPLY_CHANCE", "0.4"))
        self.keyword_reply_chance = self._clamp_probability(os.getenv("KEYWORD_REPLY_CHANCE", "0.6"))
        self.random_interjection_chance = self._clamp_probability(os.getenv("RANDOM_INTERJECTION_CHANCE", "0.02"))
        self.allowed_channel_ids = self._parse_channel_ids(os.getenv("AUTONOMY_ALLOWED_CHANNEL_IDS", ""))

    def _clamp_probability(self, raw_value: str) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, value))

    def _parse_channel_ids(self, raw: str):
        channel_ids = set()
        for item in raw.split(","):
            stripped = item.strip()
            if not stripped:
                continue
            if stripped.isdigit():
                channel_ids.add(int(stripped))
        return channel_ids

    def _is_autonomy_channel_allowed(self, channel_id: int) -> bool:
        # Empty list means unrestricted proactive behavior.
        if not self.allowed_channel_ids:
            return True
        return channel_id in self.allowed_channel_ids

    async def get_reply_reason(self, message, recent_messages: List[Dict]):
        """
        Returns the reason key for replying, or None when no reply should be sent.
        """
        mode = self.mode if self.mode in {"direct-only", "balanced", "social"} else "balanced"

        # 1. Direct Mention
        if self.bot_id in [user.id for user in message.mentions]:
            logger.info("Direct mention detected.")
            return "direct_mention"

        # 2. Reply to a message the bot sent (Unlikely unless user explicitly replies)
        if message.reference:
            resolved = message.reference.resolved
            if resolved and getattr(resolved, "author", None) and resolved.author.id == self.bot_id:
                logger.info("Reply to bot's message detected (cached reference).")
                return "direct_reply"

            # Fallback for uncached references.
            try:
                if message.reference.message_id:
                    referenced = await message.channel.fetch_message(message.reference.message_id)
                    if referenced.author.id == self.bot_id:
                        logger.info("Reply to bot's message detected (fetched reference).")
                        return "direct_reply"
            except Exception as exc:
                logger.debug("Unable to resolve replied-to message: %s", exc)

        # In direct-only mode, only explicit direct interactions can trigger a response.
        if mode == "direct-only":
            return None

        # Proactive/autonomous behavior is restricted to allowlisted channels if configured.
        if not self._is_autonomy_channel_allowed(message.channel.id):
            return None

        random_boost = 1.0 if mode == "balanced" else 1.5
        continue_chance = min(1.0, self.continue_reply_chance * random_boost)
        keyword_chance = min(1.0, self.keyword_reply_chance * random_boost)
        interjection_chance = min(1.0, self.random_interjection_chance * random_boost)

        # 3. Analyze Recent Context for "interest"
        # If the bot spoke recently (e.g., in the last 2-3 messages), it's more likely to continue.
        bot_spoke_recently = False
        # Limit to last 3
        last_few = recent_messages[-3:] if len(recent_messages) >= 3 else recent_messages

        for msg in last_few:
            if msg.get('is_bot'):
                bot_spoke_recently = True
                break

        if bot_spoke_recently:
             # Higher chance to continue conversation if bot was involved recently
             # but check if the very last message was the bot itself (don't reply to self unless prompted)
             if recent_messages and recent_messages[-1].get('is_bot'):
                 # Don't double reply usually
                 return None

             if random.random() < continue_chance:
                 logger.info("Continuing conversation (recent activity).")
                 return "continue_conversation"

        # 4. Keyword Matching (Optional - simple implementation)
        content_lower = message.content.lower()
        keywords = ["ai", "bot", "assistant", "help", "hello"]
        if any(keyword in content_lower for keyword in keywords):
            if random.random() < keyword_chance:
                 logger.info("Keyword match.")
                 return "keyword_match"

        # 5. Random Background Chance (Lurking)
        # Very low chance to just pipe up
        if random.random() < interjection_chance:
            logger.info("Random background interaction.")
            return "random_interjection"

        return None

    async def should_reply(self, message, recent_messages: List[Dict]):
        """
        Backward-compatible boolean reply decision.
        """
        reason = await self.get_reply_reason(message, recent_messages)
        return reason is not None
