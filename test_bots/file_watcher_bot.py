"""File watcher bot testing create_file_change_event.

Tests:
- create_file_change_event factory
- File modification detection
- Editable file_path attribute
"""

import asyncio
import html
import logging
import os
import sys
import tempfile
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    create_file_change_event,
)


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


# Create a test file to monitor
TEST_FILE = os.path.join(tempfile.gettempdir(), "bot_test_file.txt")


def ensure_test_file() -> str:
    """Ensure the test file exists."""
    if not os.path.exists(TEST_FILE):
        with open(TEST_FILE, "w") as f:
            f.write("Initial content\n")
    return TEST_FILE


def main() -> None:
    """Run the file watcher test bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("file_watcher_bot")

    token, chat_id = get_credentials()

    # Ensure test file exists
    test_file = ensure_test_file()
    logger.info("Monitoring file: %s", test_file)

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Create file change event
    file_event = create_file_change_event(
        event_name="file_changed",
        file_path=test_file,
        message_builder=lambda path: f"📄 File was modified!\n<code>{path}</code>",
        poll_seconds=5.0,  # Check every 5 seconds
    )
    app.register_event(file_event)

    # Command to show current file path
    app.register_command(SimpleCommand(
        command="/file",
        description="Show monitored file path",
        message_builder=lambda: f"Monitoring: <code>{file_event.get('condition.file_path')}</code>",
    ))

    # Command to touch the file (trigger change)
    def touch_file() -> str:
        """Touch the file to trigger the event."""
        current_path = file_event.get("condition.file_path")
        try:
            with open(current_path, "a") as f:
                f.write(f"Touched at {asyncio.get_event_loop().time()}\n")
            return f"✅ File touched: <code>{current_path}</code>"
        except OSError as e:
            return f"❌ Failed to touch file: {e}"

    app.register_command(SimpleCommand(
        command="/touch",
        description="Touch the file to trigger change detection",
        message_builder=touch_file,
    ))

    # Command to show file contents
    def show_contents() -> str:
        """Show the current file contents."""
        current_path = file_event.get("condition.file_path")
        try:
            with open(current_path, "r") as f:
                contents = f.read()
            if len(contents) > 500:
                contents = contents[:500] + "\n... (truncated)"
            # Escape file contents since they may contain HTML special characters
            return f"<b>File contents:</b>\n<pre>{html.escape(contents)}</pre>"
        except OSError as e:
            return f"❌ Failed to read file: {e}"

    app.register_command(SimpleCommand(
        command="/contents",
        description="Show file contents",
        message_builder=show_contents,
    ))

    # Info command
    info_text = (
        "<b>File Watcher Bot</b>\n\n"
        "Tests file change detection:\n"
        "• <code>create_file_change_event</code> factory\n"
        "• File modification time monitoring\n"
        "• Editable <code>file_path</code> attribute\n\n"
        "<b>Commands:</b>\n"
        "/file - Show monitored file path\n"
        "/touch - Touch file to trigger event\n"
        "/contents - Show file contents"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    # Send startup message and run
    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"🤖 <b>File Watcher Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting file_watcher_bot...")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
