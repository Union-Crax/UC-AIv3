# AI Discord Chatbot with OpenRouter & Autonomy

This is an advanced Discord chatbot powered by OpenRouter (LLM) with autonomous features, human-like typing behavior, and persistent context using PostgreSQL.

## Features

- **Autonomous Replies**: The bot decides when to reply based on mentions, keywords, and recent activity.
- **Human-like Behavior**: Simulates reading time, thinking pauses, and typing speed based on message length.
- **Context Awareness**: Remembers conversation history per channel using PostgreSQL.
- **Configurable AI**: Supports any OpenRouter compatible model via environment variables.

## Setup

1.  **Clone the repository**
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment**:
    - Copy `.env.example` to `.env`.
    - Fill in your `DISCORD_TOKEN`, `OPENROUTER_API_KEY`, and `DATABASE_URL`.
    - Adjust `MODEL_NAME` and `SYSTEM_PROMPT` as desired.

4.  **Database Setup**:
    - Ensure you have a PostgreSQL database running.
    - The bot will automatically create the necessary `messages` table on startup.

5.  **Run the Bot**:
    ```bash
    python3 src/main.py
    ```

## Development

- **Run Tests**:
    ```bash
    python3 tests/test_logic.py
    ```

## Structure

- `src/main.py`: Entry point.
- `src/cogs/chat.py`: Main logic for message handling and autonomy.
- `src/services/ai.py`: OpenRouter API integration.
- `src/services/db.py`: Database connection and logging.
- `src/services/autonomy.py`: Logic for deciding when to reply.
- `src/utils/humanizer.py`: Logic for typing delays and indicators.
