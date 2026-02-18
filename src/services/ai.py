import os
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

class AI:
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.model_name = os.getenv("MODEL_NAME", "anthropic/claude-3-opus")
        self.system_prompt = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY is not set. AI features will not work.")
            self.client = None
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url="https://openrouter.ai/api/v1",
            )

    async def generate_response(self, messages: list) -> str:
        if not self.client:
            return "Error: AI not configured."

        try:
            # Prepend system prompt if not present in messages or handle it here
            formatted_messages = [{"role": "system", "content": self.system_prompt}] + messages

            completion = await self.client.chat.completions.create(
                model=self.model_name,
                messages=formatted_messages,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Error generating response."

ai_service = AI()
