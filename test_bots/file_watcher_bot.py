"""File watcher bot testing create_file_change_event.

Tests:
- create_file_change_event factory
- File modification detection
- Editable file_path attribute
"""

import asyncio
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


def get_credentials():
    """Get bot credentials from environment variables."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        raise RuntimeError(
            "Missing environment variables. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )
    return token, chat_id


# Create a test file to monitor
TEST_FILE = os.path.join(tempfile.gettempdir(), "bot_test_file.txt")


def ensure_test_file():
    """Ensure the test file exists."""
    if not os.path.exists(TEST_FILE):
        with open(TEST_FILE, "w") as f:
            f.write("Initial content\n")
    return TEST_FILE


def main():
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
    def touch_file():
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
    def show_contents():
        """Show the current file contents."""
        current_path = file_event.get("condition.file_path")
        try:
            with open(current_path, "r") as f:
                contents = f.read()
            if len(contents) > 500:
                contents = contents[:500] + "\n... (truncated)"
            return f"<b>File contents:</b>\n<pre>{contents}</pre>"
        except OSError as e:
            return f"❌ Failed to read file: {e}"
    
    app.register_command(SimpleCommand(
        command="/contents",
        description="Show file contents",
        message_builder=show_contents,
    ))
    
    # Info command
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: (
            "<b>File Watcher Bot</b>\n\n"
            "Tests file change detection:\n"
            "• <code>create_file_change_event</code> factory\n"
            "• File modification time monitoring\n"
            "• Editable <code>file_path</code> attribute\n\n"
            "<b>Commands:</b>\n"
            "/file - Show monitored file path\n"
            "/touch - Touch file to trigger event\n"
            "/contents - Show file contents"
        ),
    ))
    
    logger.info("Starting file_watcher_bot...")
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
