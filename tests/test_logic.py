import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Add src to python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.autonomy import AutonomyEngine
from services.ai import AI
from utils.humanizer import Humanizer
from main import get_missing_required_env_vars


class FakeAuthor:
    def __init__(self, user_id, is_bot=False):
        self.id = user_id
        self.bot = is_bot


class FakeReferencedMessage:
    def __init__(self, author_id, author_is_bot=False):
        self.author = FakeAuthor(author_id, is_bot=author_is_bot)

async def test_humanizer():
    h = Humanizer(wpm_min=60, wpm_max=90, reading_wpm=200)

    # Test reading delay
    text = "Hello world " * 10 # 20 words
    delay = h.calculate_reading_delay(text)
    # Expected: 20/200 min = 0.1 min = 6 sec. Capped at 5s.
    assert delay <= 6.5 # includes base delay and cap behavior
    print(f"Reading delay test passed: {delay}")

    # Test typing delay
    typing_delay = h.calculate_typing_delay(text)
    # Expected: 20/60 = 20 sec max. Capped at 15s.
    assert typing_delay <= 15.0
    print(f"Typing delay test passed: {typing_delay}")

async def test_autonomy():
    with patch.dict(
        os.environ,
        {
            "AUTONOMY_MODE": "balanced",
            "AUTONOMY_ALLOWED_CHANNEL_IDS": "",
            "CONTINUE_REPLY_CHANCE": "0.4",
            "KEYWORD_REPLY_CHANCE": "0.6",
            "RANDOM_INTERJECTION_CHANCE": "0.02",
        },
        clear=False,
    ):
        engine = AutonomyEngine(bot_id=123)

        # Test mention
        msg = MagicMock()
        msg.mentions = [MagicMock(id=123)]
        msg.reference = None
        msg.channel = MagicMock()
        msg.channel.id = 111
        should = await engine.should_reply(msg, [])
        assert should == True
        print("Autonomy mention test passed.")

        # Test keyword
        msg.mentions = []
        msg.content = "Can the AI help me?"
        # Mock random to force True
        with patch('random.random', return_value=0.1):
            should = await engine.should_reply(msg, [])
            assert should == True
        print("Autonomy keyword test passed.")

        # Test ignore
        msg.content = "Just chatting."
        with patch('random.random', return_value=0.99):
            should = await engine.should_reply(msg, [])
            assert should == False
        print("Autonomy ignore test passed.")

        # Test fallback fetch for reply references when resolved message is not cached
        msg.mentions = []
        msg.content = "replying"
        msg.reference = MagicMock()
        msg.reference.resolved = None
        msg.reference.message_id = 456
        msg.channel.fetch_message = AsyncMock(return_value=FakeReferencedMessage(123))
        should = await engine.should_reply(msg, [])
        assert should == True
        print("Autonomy reply-reference fallback test passed.")

    # direct-only mode should block non-direct proactive replies
    with patch.dict(os.environ, {"AUTONOMY_MODE": "direct-only"}, clear=False):
        engine = AutonomyEngine(bot_id=123)
        msg = MagicMock()
        msg.mentions = []
        msg.content = "hello"
        msg.reference = None
        msg.channel = MagicMock()
        msg.channel.id = 222
        with patch('random.random', return_value=0.0):
            should = await engine.should_reply(msg, [])
            assert should == False
        print("Autonomy direct-only mode test passed.")

    # allowlist should block proactive replies in non-allowlisted channels
    with patch.dict(
        os.environ,
        {
            "AUTONOMY_MODE": "balanced",
            "AUTONOMY_ALLOWED_CHANNEL_IDS": "999",
        },
        clear=False,
    ):
        engine = AutonomyEngine(bot_id=123)
        msg = MagicMock()
        msg.mentions = []
        msg.content = "hello ai"
        msg.reference = None
        msg.channel = MagicMock()
        msg.channel.id = 123456
        with patch('random.random', return_value=0.0):
            should = await engine.should_reply(msg, [])
            assert should == False
        print("Autonomy allowlist test passed.")

    # should not proactively jump in when message is directed at another bot
    with patch.dict(
        os.environ,
        {
            "AUTONOMY_MODE": "social",
            "AUTONOMY_ALLOWED_CHANNEL_IDS": "",
            "RANDOM_INTERJECTION_CHANCE": "1.0",
            "PROACTIVE_COOLDOWN_SECONDS": "0",
        },
        clear=False,
    ):
        engine = AutonomyEngine(bot_id=123)
        msg = MagicMock()
        msg.mentions = [MagicMock(id=999, bot=True)]
        msg.content = "@OtherBot can you help"
        msg.reference = None
        msg.channel = MagicMock()
        msg.channel.id = 333
        with patch('random.random', return_value=0.0):
            should = await engine.should_reply(msg, [])
            assert should == False
        print("Autonomy target-other-bot guard test passed.")

    # if user explicitly mentions this bot, it should still reply even when another bot is referenced
    with patch.dict(
        os.environ,
        {
            "AUTONOMY_MODE": "social",
            "AUTONOMY_ALLOWED_CHANNEL_IDS": "",
            "RANDOM_INTERJECTION_CHANCE": "1.0",
            "PROACTIVE_COOLDOWN_SECONDS": "0",
        },
        clear=False,
    ):
        engine = AutonomyEngine(bot_id=123)
        msg = MagicMock()
        msg.mentions = [MagicMock(id=999, bot=True), MagicMock(id=123, bot=True)]
        msg.content = "i was talking to <@123>"
        msg.reference = MagicMock()
        msg.reference.resolved = FakeReferencedMessage(999, author_is_bot=True)
        msg.reference.message_id = 111
        msg.channel = MagicMock()
        msg.channel.id = 334
        should = await engine.should_reply(msg, [])
        assert should == True
        print("Autonomy explicit-self-mention override test passed.")

    # weighted proactive signal should trigger even without direct mention
    with patch.dict(
        os.environ,
        {
            "AUTONOMY_MODE": "balanced",
            "AUTONOMY_ALLOWED_CHANNEL_IDS": "",
            "PROACTIVE_SCORE_THRESHOLD": "0.5",
            "SIGNAL_QUESTION_BONUS": "0.3",
            "SIGNAL_ENGAGEMENT_BONUS": "0.3",
            "SIGNAL_KEYWORD_BONUS": "0.3",
            "PROACTIVE_COOLDOWN_SECONDS": "0",
        },
        clear=False,
    ):
        engine = AutonomyEngine(bot_id=123)
        msg = MagicMock()
        msg.mentions = []
        msg.content = "anyone know why this bug is happening?"
        msg.reference = None
        msg.channel = MagicMock()
        msg.channel.id = 777
        should = await engine.should_reply(msg, [])
        assert should == True
        print("Autonomy weighted proactive signal test passed.")

    # proactive cooldown should suppress immediate repeated jump-ins in same channel
    with patch.dict(
        os.environ,
        {
            "AUTONOMY_MODE": "balanced",
            "AUTONOMY_ALLOWED_CHANNEL_IDS": "",
            "RANDOM_INTERJECTION_CHANCE": "1.0",
            "PROACTIVE_COOLDOWN_SECONDS": "999",
        },
        clear=False,
    ):
        engine = AutonomyEngine(bot_id=123)
        msg = MagicMock()
        msg.mentions = []
        msg.content = "random chat"
        msg.reference = None
        msg.channel = MagicMock()
        msg.channel.id = 888
        with patch('random.random', return_value=0.0):
            first = await engine.should_reply(msg, [])
            second = await engine.should_reply(msg, [])
        assert first == True
        assert second == False
        print("Autonomy proactive cooldown test passed.")


def test_required_env_validation():
    with patch.dict(os.environ, {"DISCORD_TOKEN": "", "OPENROUTER_API_KEY": "k", "DATABASE_URL": "db"}, clear=False):
        missing = get_missing_required_env_vars()
        assert "DISCORD_TOKEN" in missing

    with patch.dict(
        os.environ,
        {"DISCORD_TOKEN": "t", "OPENROUTER_API_KEY": "k", "DATABASE_URL": "postgres://localhost/db"},
        clear=False,
    ):
        missing = get_missing_required_env_vars()
        assert missing == []

    print("Required env validation tests passed.")


def test_ai_sanitizer():
    ai = AI()

    messy = "*looks away* hey #wewebrosmatter #wewebrosmatter #wewebrosmatter status is up."
    cleaned = ai._sanitize_response(messy)
    assert "*looks away*" not in cleaned
    assert cleaned.count("#wewebrosmatter") <= 1

    long_text = "One. Two. Three. Four. Five."
    cleaned_long = ai._sanitize_response(long_text)
    assert cleaned_long.count(".") <= ai.max_response_sentences

    print("AI sanitizer tests passed.")

if __name__ == "__main__":
    asyncio.run(test_humanizer())
    asyncio.run(test_autonomy())
    test_required_env_validation()
    test_ai_sanitizer()
