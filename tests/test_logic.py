import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Add src to python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.autonomy import AutonomyEngine
from utils.humanizer import Humanizer
from main import get_missing_required_env_vars


class FakeAuthor:
    def __init__(self, user_id):
        self.id = user_id


class FakeReferencedMessage:
    def __init__(self, author_id):
        self.author = FakeAuthor(author_id)

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
    engine = AutonomyEngine(bot_id=123)

    # Test mention
    msg = MagicMock()
    msg.mentions = [MagicMock(id=123)]
    msg.reference = None
    msg.channel = MagicMock()
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

if __name__ == "__main__":
    asyncio.run(test_humanizer())
    asyncio.run(test_autonomy())
    test_required_env_validation()
