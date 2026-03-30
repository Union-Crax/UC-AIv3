import os
import logging
import asyncio
import re
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

logger = logging.getLogger(__name__)

class AI:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model_name = os.getenv("MODEL_NAME", "llama3-8b-8192")
        self.system_prompt = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")
        self.max_response_tokens = self._parse_int_env("MAX_RESPONSE_TOKENS", default=256, min_value=32, max_value=4096)
        self.max_response_chars = self._parse_int_env("MAX_RESPONSE_CHARS", default=260, min_value=80, max_value=1200)
        self.max_response_sentences = self._parse_int_env("MAX_RESPONSE_SENTENCES", default=3, min_value=1, max_value=8)
        self.temperature = self._parse_float_env("MODEL_TEMPERATURE", default=0.5, min_value=0.0, max_value=1.5)

        if not self.api_key:
            logger.warning("GROQ_API_KEY is not set. AI features will not work.")
            self.client = None
        elif AsyncOpenAI is None:
            logger.warning("openai package is not installed. AI features will not work until dependencies are installed.")
            self.client = None
        else:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url="https://api.groq.com/openai/v1",
            )

    def _parse_int_env(self, key: str, default: int, min_value: int, max_value: int) -> int:
        raw_value = os.getenv(key)
        if raw_value is None:
            return default
        try:
            parsed = int(raw_value)
        except ValueError:
            logger.warning("Invalid %s=%r; using default %s", key, raw_value, default)
            return default
        return max(min_value, min(parsed, max_value))

    def _parse_float_env(self, key: str, default: float, min_value: float, max_value: float) -> float:
        raw_value = os.getenv(key)
        if raw_value is None:
            return default
        try:
            parsed = float(raw_value)
        except ValueError:
            logger.warning("Invalid %s=%r; using default %.2f", key, raw_value, default)
            return default
        return max(min_value, min(parsed, max_value))

    def _trim_to_sentence_limit(self, text: str) -> str:
        if self.max_response_sentences <= 0:
            return text
        chunks = re.split(r'([.!?]+\s*)', text)
        if len(chunks) <= 1:
            return text

        sentence_count = 0
        output_parts = []
        i = 0
        while i < len(chunks):
            output_parts.append(chunks[i])
            if i + 1 < len(chunks):
                output_parts.append(chunks[i + 1])
                sentence_count += 1
                if sentence_count >= self.max_response_sentences:
                    break
            i += 2
        return "".join(output_parts).strip()

    def _sanitize_response(self, text: str) -> str:
        if not text:
            return ""

        # Remove roleplay/action stage directions and collapse whitespace.
        sanitized = re.sub(r'\*[^*]{1,120}\*', '', text)
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()

        # Remove hashtag spam by keeping at most one instance per hashtag.
        seen_hashtags = set()
        rebuilt_tokens = []
        for token in sanitized.split(' '):
            if token.startswith('#') and len(token) > 1:
                key = token.lower()
                if key in seen_hashtags:
                    continue
                seen_hashtags.add(key)
            rebuilt_tokens.append(token)
        sanitized = " ".join(rebuilt_tokens)

        sanitized = self._trim_to_sentence_limit(sanitized)

        if len(sanitized) > self.max_response_chars:
            sanitized = sanitized[: self.max_response_chars].rstrip()

        return sanitized.strip()

    def _is_retryable_error(self, error: Exception) -> bool:
        status_code = getattr(error, "status_code", None)
        if status_code is not None:
            if status_code in {400, 401, 402, 403, 404, 422}:
                return False
            if status_code in {408, 409, 429, 500, 502, 503, 504}:
                return True
        return True

    async def classify(self, question: str) -> bool:
        """
        Ask the model a yes/no question. Returns True for YES, False for NO/error.
        Uses a minimal prompt with no system context to keep it fast and cheap.
        """
        if not self.client:
            return False
        try:
            completion = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "Answer only YES or NO. No explanation, no punctuation.",
                    },
                    {"role": "user", "content": question},
                ],
                max_tokens=2,
                temperature=0.0,
                timeout=10,
            )
            answer = (completion.choices[0].message.content or "").strip().upper()
            return answer.startswith("YES")
        except Exception as exc:
            logger.debug("classify() failed: %s", exc)
            return False

    async def generate_response(self, messages: list) -> str:
        if not self.client:
            return "Error: AI not configured."

        # Prepend system prompt if not present in messages or handle it here.
        formatted_messages = [{"role": "system", "content": self.system_prompt}] + messages

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                completion = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=formatted_messages,
                    max_tokens=self.max_response_tokens,
                    temperature=self.temperature,
                    timeout=45,
                )
                content = completion.choices[0].message.content or ""
                sanitized = self._sanitize_response(content)
                if not sanitized:
                    return "Got you."
                return sanitized
            except Exception as e:
                if not self._is_retryable_error(e):
                    status_code = getattr(e, "status_code", "unknown")
                    logger.error(
                        "AI request failed with non-retryable error (status=%s): %s",
                        status_code,
                        e,
                    )
                    return "I could not generate a response right now. Try lowering MAX_RESPONSE_TOKENS or checking OpenRouter credits."

                is_last_attempt = attempt == max_attempts
                logger.warning("AI request failed (attempt %s/%s): %s", attempt, max_attempts, e)
                if is_last_attempt:
                    logger.error("Error generating response after retries.")
                    return "I hit a temporary issue generating a response. Please try again."

                # Simple exponential backoff for transient upstream issues.
                await asyncio.sleep(2 ** (attempt - 1))

ai_service = AI()
