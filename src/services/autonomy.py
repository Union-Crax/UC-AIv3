import random
import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class AutonomyEngine:
    def __init__(self, bot_id: int):
        self.bot_id = bot_id
        # Simple interest score or state could be added here
        self.interest_level = 0.0

    async def should_reply(self, message, recent_messages: List[Dict]):
        """
        Decides whether to reply to a message based on context.
        """
        # 1. Direct Mention
        if self.bot_id in [user.id for user in message.mentions]:
            logger.info("Direct mention detected.")
            return True

        # 2. Reply to a message the bot sent (Unlikely unless user explicitly replies)
        if message.reference:
            # Note: resolved might be None if message not in cache, but we can try to fetch or check message_id
             # For simplicity, if resolved is available:
            if message.reference.resolved and message.reference.resolved.author.id == self.bot_id:
                 logger.info("Reply to bot's message detected.")
                 return True

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
                 return False

             if random.random() < 0.4: # 40% chance to continue
                 logger.info("Continuing conversation (recent activity).")
                 return True

        # 4. Keyword Matching (Optional - simple implementation)
        content_lower = message.content.lower()
        keywords = ["ai", "bot", "assistant", "help", "hello"]
        if any(keyword in content_lower for keyword in keywords):
            if random.random() < 0.6: # 60% chance if keyword found
                 logger.info("Keyword match.")
                 return True

        # 5. Random Background Chance (Lurking)
        # Very low chance to just pipe up
        if random.random() < 0.02: # 2% chance
            logger.info("Random background interaction.")
            return True

        return False
