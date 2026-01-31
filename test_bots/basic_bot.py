"""Basic bot testing TimeEvent and SimpleCommand.

Tests:
- BotApplication initialization
- TimeEvent with fire_on_first_check
- SimpleCommand registration
- Built-in /terminate and /commands
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import BotApplication, SimpleCommand, TimeEvent


def get_credentials():
    """Get bot credentials from environment variables."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        raise RuntimeError(
            "Missing environment variables. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )
    return token, chat_id


def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("basic_bot")
    
    token, chat_id = get_credentials()
    
    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )
    
    # Register a simple command
    app.register_command(SimpleCommand(
        command="/hello",
        description="Say hello",
        message_builder=lambda: "Hello from basic_bot!",
    ))
    
    # Register a status command
    app.register_command(SimpleCommand(
        command="/status",
        description="Show bot status",
        message_builder=lambda: "Bot is running normally.",
    ))
    
    # Register a time-based event (every 5 minutes, fire immediately)
    app.register_event(TimeEvent(
        title="heartbeat",
        interval_hours=5.0 / 60.0,  # 5 minutes
        message_builder=lambda: "Heartbeat: Bot is alive!",
        fire_on_first_check=True,
    ))
    
    logger.info("Starting basic_bot...")
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
