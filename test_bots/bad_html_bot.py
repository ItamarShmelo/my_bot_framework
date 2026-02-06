"""Test bot that sends invalid HTML to demonstrate InvalidHtmlError.

Tests:
- InvalidHtmlError is raised when sending unescaped HTML
- Fatal error propagates up and terminates the bot
- CRITICAL-level log with full traceback is produced

Usage:
    Start the bot and send /bad_html. The bot will attempt to send a message
    containing raw '<' and '>' characters, which Telegram cannot parse as HTML.
    This triggers InvalidHtmlError, which propagates up and terminates the bot
    with a CRITICAL log and full traceback.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import BotApplication, SimpleCommand


def get_credentials() -> tuple[str, str]:
    """Get bot credentials from .token and .chat_id files in test_bots directory.

    Returns:
        Tuple of (token, chat_id) from credential files.

    Raises:
        RuntimeError: If .token or .chat_id files are missing or empty.
    """
    test_bots_dir = Path(__file__).resolve().parent
    token_file = test_bots_dir / ".token"
    chat_id_file = test_bots_dir / ".chat_id"

    if not token_file.exists() or not chat_id_file.exists():
        raise RuntimeError(
            "Missing credential files. Create .token and .chat_id files in test_bots directory."
        )

    token = token_file.read_text().strip()
    chat_id = chat_id_file.read_text().strip()

    if not token or not chat_id:
        raise RuntimeError(
            "Empty credential files. Ensure .token and .chat_id contain valid values."
        )
    return token, chat_id


def bad_html_message() -> str:
    """Return a message with unescaped HTML that will trigger InvalidHtmlError."""
    return "This has <invalid> HTML tags like <b>unclosed and <not_a_tag> characters"


def main() -> None:
    """Run the bad HTML test bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("bad_html_bot")

    token, chat_id = get_credentials()
    app = BotApplication.initialize(token=token, chat_id=chat_id, logger=logger)

    # Register info command
    info_text = (
        "<b>Bad HTML Bot</b>\n\n"
        "Tests InvalidHtmlError handling:\n"
        "• InvalidHtmlError is raised when sending unescaped HTML\n"
        "• Fatal error propagates up and terminates the bot\n"
        "• CRITICAL-level log with full traceback is produced"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    app.register_command(SimpleCommand(
        command="/bad_html",
        description="Send a message with invalid HTML (triggers fatal InvalidHtmlError).",
        message_builder=bad_html_message,
    ))

    # Send startup message and run
    async def send_startup_and_run() -> None:
        """Send startup message and run the bot."""
        await app.send_messages(
            f"⚠️ <b>Bad HTML Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /bad_html to trigger InvalidHtmlError (will terminate the bot)."
        )
        logger.info("send_startup_and_run: starting")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
