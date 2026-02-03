"""Document bot testing TelegramDocumentMessage.

Tests:
- TelegramDocumentMessage class
- Sending documents with and without captions
- HTML caption support
- Error handling for missing files
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Tuple

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    TelegramDocumentMessage,
)


def get_credentials() -> Tuple[str, str]:
    """Get bot credentials from .token and .chat_id files in test_bots directory."""
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


# Create a temporary test file for document sending
def create_test_file() -> Path:
    """Create a temporary test file for document sending."""
    test_bots_dir = Path(__file__).resolve().parent
    test_file = test_bots_dir / "test_document.txt"
    test_file.write_text(
        "This is a test document.\n"
        "Created by document_bot.py\n"
        "Used to test TelegramDocumentMessage functionality.\n"
    )
    return test_file


def main() -> None:
    """Run the document test bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("document_bot")

    token, chat_id = get_credentials()

    # Create test file
    test_file = create_test_file()
    logger.info("Created test file at %s", test_file)

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Command: Send document without caption
    async def send_plain_document() -> TelegramDocumentMessage:
        """Send a document without caption."""
        return TelegramDocumentMessage(test_file)

    app.register_command(SimpleCommand(
        command="/doc",
        description="Send a document without caption",
        message_builder=send_plain_document,
    ))

    # Command: Send document with plain caption
    async def send_document_with_caption() -> TelegramDocumentMessage:
        """Send a document with a plain text caption."""
        return TelegramDocumentMessage(
            test_file,
            caption="Here is the test document.",
        )

    app.register_command(SimpleCommand(
        command="/doc_caption",
        description="Send a document with plain caption",
        message_builder=send_document_with_caption,
    ))

    # Command: Send document with HTML caption
    async def send_document_html_caption() -> TelegramDocumentMessage:
        """Send a document with an HTML-formatted caption."""
        return TelegramDocumentMessage(
            test_file,
            caption="<b>Test Document</b>\n\n<i>This caption uses HTML formatting.</i>",
        )

    app.register_command(SimpleCommand(
        command="/doc_html",
        description="Send a document with HTML caption",
        message_builder=send_document_html_caption,
    ))

    # Command: Send document using string path
    async def send_document_string_path() -> TelegramDocumentMessage:
        """Send a document using a string path instead of Path object."""
        return TelegramDocumentMessage(
            str(test_file),
            caption="Sent using string path.",
        )

    app.register_command(SimpleCommand(
        command="/doc_string",
        description="Send document using string path",
        message_builder=send_document_string_path,
    ))

    # Command: Test error handling with missing file
    async def send_missing_document() -> TelegramDocumentMessage:
        """Attempt to send a non-existent file to test error handling."""
        return TelegramDocumentMessage(
            "/nonexistent/file.txt",
            caption="This should fail.",
        )

    app.register_command(SimpleCommand(
        command="/doc_error",
        description="Test error handling (missing file)",
        message_builder=send_missing_document,
    ))

    # Info command
    info_text = (
        "<b>Document Bot</b>\n\n"
        "Tests TelegramDocumentMessage functionality:\n"
        "• Sending documents without caption\n"
        "• Sending documents with plain caption\n"
        "• Sending documents with HTML caption\n"
        "• String vs Path file paths\n"
        "• Error handling for missing files"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    # Send startup message and run
    async def send_startup_and_run() -> None:
        """Send startup message and run the bot."""
        await app.send_messages(
            f"📄 <b>Document Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting document_bot...")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
