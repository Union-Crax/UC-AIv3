import random
import logging
import os
import time
from typing import List, Dict

logger = logging.getLogger(__name__)

class AutonomyEngine:
    def __init__(self, bot_id: int):
        self.bot_id = bot_id
        self.mode = os.getenv("AUTONOMY_MODE", "balanced").strip().lower()
        self.continue_reply_chance = self._clamp_probability(os.getenv("CONTINUE_REPLY_CHANCE", "0.4"))
        self.keyword_reply_chance = self._clamp_probability(os.getenv("KEYWORD_REPLY_CHANCE", "0.6"))
        self.random_interjection_chance = self._clamp_probability(os.getenv("RANDOM_INTERJECTION_CHANCE", "0.02"))
        self.proactive_score_threshold = self._clamp_probability(os.getenv("PROACTIVE_SCORE_THRESHOLD", "0.65"))
        self.signal_question_bonus = self._clamp_probability(os.getenv("SIGNAL_QUESTION_BONUS", "0.25"))
        self.signal_engagement_bonus = self._clamp_probability(os.getenv("SIGNAL_ENGAGEMENT_BONUS", "0.20"))
        self.signal_keyword_bonus = self._clamp_probability(os.getenv("SIGNAL_KEYWORD_BONUS", "0.30"))
        self.signal_recent_bot_bonus = self._clamp_probability(os.getenv("SIGNAL_RECENT_BOT_BONUS", "0.20"))
        self.proactive_cooldown_seconds = self._parse_int_env("PROACTIVE_COOLDOWN_SECONDS", 45, 0, 3600)
        self.allowed_channel_ids = self._parse_channel_ids(os.getenv("AUTONOMY_ALLOWED_CHANNEL_IDS", ""))
        self.last_proactive_reply_by_channel = {}
        # Friendly-fire: bot IDs that are allowed to interact directly with this bot.
        self.friendly_bot_ids = self._parse_channel_ids(os.getenv("FRIENDLY_BOT_IDS", ""))
        self.bot_convo_max_turns = self._parse_int_env("BOT_CONVO_MAX_TURNS", 6, 1, 20)
        self._bot_convo_turns_by_channel: dict = {}

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

    def _parse_int_env(self, key: str, default: int, min_value: int, max_value: int) -> int:
        raw_value = os.getenv(key)
        if raw_value is None:
            return default
        try:
            parsed = int(raw_value)
        except ValueError:
            return default
        return max(min_value, min(parsed, max_value))

    def _is_friendly_bot(self, user_id: int) -> bool:
        return user_id in self.friendly_bot_ids

    def _record_bot_turn(self, channel_id: int):
        self._bot_convo_turns_by_channel[channel_id] = self._bot_convo_turns_by_channel.get(channel_id, 0) + 1

    def _reset_bot_turns(self, channel_id: int):
        self._bot_convo_turns_by_channel.pop(channel_id, None)

    def _bot_turns_exceeded(self, channel_id: int) -> bool:
        return self._bot_convo_turns_by_channel.get(channel_id, 0) >= self.bot_convo_max_turns

    def _cooldown_active(self, channel_id: int) -> bool:
        if self.proactive_cooldown_seconds <= 0:
            return False
        last_reply_ts = self.last_proactive_reply_by_channel.get(channel_id)
        if last_reply_ts is None:
            return False
        return (time.time() - last_reply_ts) < self.proactive_cooldown_seconds

    def _mark_proactive_reply(self, channel_id: int):
        self.last_proactive_reply_by_channel[channel_id] = time.time()

    def _contains_question_signal(self, content_lower: str) -> bool:
        if "?" in content_lower:
            return True
        starters = ("how ", "why ", "what ", "who ", "where ", "when ", "can ", "could ", "should ", "does ", "is ", "any ")
        return content_lower.startswith(starters)

    def _contains_engagement_signal(self, content_lower: str) -> bool:
        engagement_terms = ["thoughts", "opinion", "idea", "anyone know", "help", "fix", "bug", "issue", "wtf", "error", "stuck"]
        return any(term in content_lower for term in engagement_terms)

    def _contains_keyword_signal(self, content_lower: str) -> bool:
        keywords = ["ai", "bot", "assistant", "unioncrax", "uc-ai", "uc ai", "status", "reddit", "forum", "forums"]
        return any(keyword in content_lower for keyword in keywords)

    def _targets_other_bot(self, message) -> bool:
        """
        Return True when message appears directed to a non-friendly bot account.
        Friendly bots (FRIENDLY_BOT_IDS) are exempted so humans conversing with
        them can still attract proactive jump-ins.
        """
        mentions = getattr(message, "mentions", [])

        # Explicitly addressing this bot should always be handled as direct input.
        if any(getattr(mentioned_user, "id", None) == self.bot_id for mentioned_user in mentions):
            return False

        for mentioned_user in mentions:
            uid = getattr(mentioned_user, "id", None)
            if uid != self.bot_id and getattr(mentioned_user, "bot", False) and not self._is_friendly_bot(uid):
                return True

        if message.reference:
            resolved = message.reference.resolved
            if resolved and getattr(resolved, "author", None):
                author = resolved.author
                uid = getattr(author, "id", None)
                if uid != self.bot_id and getattr(author, "bot", False) and not self._is_friendly_bot(uid):
                    return True

        return False

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

        sender_is_bot = message.author.bot
        sender_is_friendly = sender_is_bot and self._is_friendly_bot(message.author.id)

        # Reset bot-conversation turn counter whenever a human speaks.
        if not sender_is_bot:
            self._reset_bot_turns(message.channel.id)

        # 1. Direct Mention
        if self.bot_id in [user.id for user in message.mentions]:
            if sender_is_bot and not sender_is_friendly:
                # Non-friendly bots cannot engage this bot even via direct mention.
                return None
            if sender_is_friendly:
                if self._bot_turns_exceeded(message.channel.id):
                    logger.info("Friendly-fire turn limit reached; disengaging from bot conversation.")
                    return None
                self._record_bot_turn(message.channel.id)
            logger.info("Direct mention detected.")
            return "direct_mention"

        # 2. Reply to a message the bot sent (Unlikely unless user explicitly replies)
        if message.reference:
            resolved = message.reference.resolved
            if resolved and getattr(resolved, "author", None) and resolved.author.id == self.bot_id:
                if sender_is_bot and not sender_is_friendly:
                    return None
                if sender_is_friendly:
                    if self._bot_turns_exceeded(message.channel.id):
                        logger.info("Friendly-fire turn limit reached; disengaging from bot conversation.")
                        return None
                    self._record_bot_turn(message.channel.id)
                logger.info("Reply to bot's message detected (cached reference).")
                return "direct_reply"

            # Fallback for uncached references.
            try:
                if message.reference.message_id:
                    referenced = await message.channel.fetch_message(message.reference.message_id)
                    if referenced.author.id == self.bot_id:
                        if sender_is_bot and not sender_is_friendly:
                            return None
                        if sender_is_friendly:
                            if self._bot_turns_exceeded(message.channel.id):
                                logger.info("Friendly-fire turn limit reached; disengaging from bot conversation.")
                                return None
                            self._record_bot_turn(message.channel.id)
                        logger.info("Reply to bot's message detected (fetched reference).")
                        return "direct_reply"
            except Exception as exc:
                logger.debug("Unable to resolve replied-to message: %s", exc)

        # Non-friendly bot messages beyond direct interactions are ignored.
        if sender_is_bot:
            return None

        # In direct-only mode, only explicit direct interactions can trigger a response.
        if mode == "direct-only":
            return None

        # If user is targeting another bot, do not proactively jump in.
        if self._targets_other_bot(message):
            logger.info("Skipping proactive reply: message appears targeted at another bot.")
            return None

        # Proactive/autonomous behavior is restricted to allowlisted channels if configured.
        if not self._is_autonomy_channel_allowed(message.channel.id):
            return None

        if self._cooldown_active(message.channel.id):
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
                 self._mark_proactive_reply(message.channel.id)
                 return "continue_conversation"

        # 4. Weighted signal matching for proactive jump-ins.
        content_lower = message.content.lower()
        score = 0.0

        if self._contains_question_signal(content_lower):
            score += self.signal_question_bonus

        if self._contains_engagement_signal(content_lower):
            score += self.signal_engagement_bonus

        keyword_signal = self._contains_keyword_signal(content_lower)
        if keyword_signal:
            score += self.signal_keyword_bonus

        if bot_spoke_recently:
            score += self.signal_recent_bot_bonus

        if mode == "social":
            score = min(1.0, score * 1.2)

        if keyword_signal and random.random() < keyword_chance and score >= (self.proactive_score_threshold * 0.8):
            logger.info("Proactive keyword signal matched (score=%.2f).", score)
            self._mark_proactive_reply(message.channel.id)
            return "keyword_match"

        if score >= self.proactive_score_threshold:
            logger.info("Proactive weighted signal matched (score=%.2f).", score)
            self._mark_proactive_reply(message.channel.id)
            return "proactive_signal"

        # 5. Random Background Chance (Lurking)
        # Very low chance to just pipe up
        if random.random() < interjection_chance:
            logger.info("Random background interaction.")
            self._mark_proactive_reply(message.channel.id)
            return "random_interjection"

        return None

    async def should_reply(self, message, recent_messages: List[Dict]):
        """
        Backward-compatible boolean reply decision.
        """
        reason = await self.get_reply_reason(message, recent_messages)
        return reason is not None
