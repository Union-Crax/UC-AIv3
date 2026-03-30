import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
DOTENV_PATH = os.path.join(ROOT_DIR, ".env")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from services.db import db  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    # Load project-local .env explicitly to avoid cwd-dependent behavior.
    load_dotenv(dotenv_path=DOTENV_PATH, override=False)

    # If a shell variable exists but is blank, let .env replace it for local runs.
    if not os.getenv("DATABASE_URL"):
        load_dotenv(dotenv_path=DOTENV_PATH, override=True)

    if not os.getenv("DATABASE_URL"):
        logger.error("DATABASE_URL is not set.")
        raise SystemExit(1)

    try:
        await db.connect()
        logger.info("Database setup completed successfully.")
    except Exception as exc:
        logger.error("Database setup failed: %s", exc)
        raise SystemExit(1)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
