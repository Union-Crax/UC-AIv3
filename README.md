# AI Discord Chatbot with OpenRouter & Autonomy

This is an advanced Discord chatbot powered by OpenRouter (LLM) with autonomous features, human-like typing behavior, and persistent context using PostgreSQL.

## Features

- **Autonomous Replies**: The bot decides when to reply based on mentions, keywords, and recent activity.
- **Human-like Behavior**: Simulates reading time, thinking pauses, and typing speed based on message length.
- **Context Awareness**: Remembers conversation history per channel using PostgreSQL.
- **Configurable AI**: Supports any OpenRouter compatible model via environment variables.
- **Fail-Fast Startup**: Exits immediately if required environment variables or PostgreSQL connectivity are missing.
- **Autonomy Modes**: Can reply only when directly addressed or also join conversations autonomously.
- **Channel Allowlist for Autonomy**: Autonomous jump-ins can be restricted to selected channel IDs.
- **Context Isolation Option**: Can keep memory shared by channel or isolated per user within a channel.

## Setup

1.  **Clone the repository**
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
        - Create a `.env` file in the project root.
        - Required:
            - `DISCORD_TOKEN`
            - `OPENROUTER_API_KEY`
            - `DATABASE_URL`
        - Optional:
            - `MODEL_NAME` (default: `anthropic/claude-3-opus`)
            - `MAX_RESPONSE_TOKENS` (default `256`, helps control OpenRouter cost and 402 token-limit failures)
            - `SYSTEM_PROMPT` (default: `You are a helpful assistant.`)
            - `AUTONOMY_MODE` (`direct-only`, `balanced`, `social`; default `balanced`)
            - `AUTONOMY_ALLOWED_CHANNEL_IDS` (comma-separated channel IDs for autonomous replies)
            - `CONTINUE_REPLY_CHANCE` (default `0.4`)
            - `KEYWORD_REPLY_CHANCE` (default `0.6`)
            - `RANDOM_INTERJECTION_CHANCE` (default `0.02`)
            - `CONTEXT_ISOLATION_MODE` (`channel`, `channel_user`, or `smart`; default `smart`)

4.  **Database Setup**:
    - Ensure you have a PostgreSQL database running.
    - The bot will automatically create the necessary `messages` table and indexes on startup.
    - If database connection fails, startup exits by design.
        - Optional preflight check:
            ```bash
            python setup_db.py
            ```

5.  **Run the Bot**:
    ```bash
     python -m src.main
    ```

## Linux/VPS Quick Start

1. Install Python 3.10+.
2. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3. Export required environment variables or provide them in `.env`.
4. Start with:
    ```bash
    python -m src.main
    ```
5. Confirm startup logs include:
    - `Connected to the database.`
    - `Bot setup complete.`
    - `Logged in as ...`

If startup exits immediately, verify required env vars and PostgreSQL reachability first.

## Development

- **Run Tests**:
    ```bash
    python tests/test_logic.py
    ```

## Production Notes

- Direct mentions and direct replies to the bot are always handled.
- Autonomous participation is controlled by `AUTONOMY_MODE` and channel allowlist settings.
- If `AUTONOMY_ALLOWED_CHANNEL_IDS` is set, autonomous (non-direct) replies only occur in listed channels.
- `CONTEXT_ISOLATION_MODE=smart` makes direct ping/reply use per-user memory and proactive jump-ins use shared channel memory.
- To force strict no-mixing behavior everywhere, set `CONTEXT_ISOLATION_MODE=channel_user`.

## Structure

- `src/main.py`: Entry point.
- `src/cogs/chat.py`: Main logic for message handling and autonomy.
- `src/services/ai.py`: OpenRouter API integration.
- `src/services/db.py`: Database connection and logging.
- `src/services/autonomy.py`: Logic for deciding when to reply.
- `src/utils/humanizer.py`: Logic for typing delays and indicators.
