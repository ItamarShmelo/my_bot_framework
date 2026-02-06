"""Reply keyboard bot testing TelegramReplyKeyboardMessage and TelegramRemoveReplyKeyboardMessage.

Tests:
- TelegramReplyKeyboardMessage class
- TelegramRemoveReplyKeyboardMessage class
- Persistent reply keyboard display
- resize_keyboard parameter
- one_time_keyboard parameter
- Combined parameters (one_time_keyboard + resize_keyboard)
- HTML formatting in message text
- Keyboard removal
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
    TelegramReplyKeyboardMessage,
    TelegramRemoveReplyKeyboardMessage,
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


def main() -> None:
    """Run the reply keyboard test bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("reply_keyboard_bot")

    token, chat_id = get_credentials()

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Command: Show simple reply keyboard
    async def show_simple_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a simple 2x2 reply keyboard."""
        keyboard = [
            ["Option A", "Option B"],
            ["Option C", "Option D"],
        ]
        return TelegramReplyKeyboardMessage(
            text="Choose an option from the keyboard below:",
            keyboard=keyboard,
        )

    app.register_command(SimpleCommand(
        command="/keyboard",
        description="Show a simple 2x2 reply keyboard",
        message_builder=show_simple_keyboard,
    ))

    # Command: Show single row keyboard
    async def show_row_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a single row reply keyboard."""
        keyboard = [
            ["Yes", "No", "Maybe"],
        ]
        return TelegramReplyKeyboardMessage(
            text="Quick response options:",
            keyboard=keyboard,
        )

    app.register_command(SimpleCommand(
        command="/row",
        description="Show a single row reply keyboard",
        message_builder=show_row_keyboard,
    ))

    # Command: Show single column keyboard
    async def show_column_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a single column reply keyboard."""
        keyboard = [
            ["First option"],
            ["Second option"],
            ["Third option"],
            ["Fourth option"],
        ]
        return TelegramReplyKeyboardMessage(
            text="Select from the list:",
            keyboard=keyboard,
        )

    app.register_command(SimpleCommand(
        command="/column",
        description="Show a single column reply keyboard",
        message_builder=show_column_keyboard,
    ))

    # Command: Show one-time keyboard (hides after selection)
    async def show_onetime_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a one-time reply keyboard that hides after use."""
        keyboard = [
            ["Confirm", "Cancel"],
        ]
        return TelegramReplyKeyboardMessage(
            text="This keyboard will hide after you tap a button:",
            keyboard=keyboard,
            one_time_keyboard=True,
        )

    app.register_command(SimpleCommand(
        command="/onetime",
        description="Show a one-time keyboard (hides after use)",
        message_builder=show_onetime_keyboard,
    ))

    # Command: Show keyboard without resize
    async def show_noresize_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a keyboard without resize (full-size buttons)."""
        keyboard = [
            ["Tall Button 1"],
            ["Tall Button 2"],
        ]
        return TelegramReplyKeyboardMessage(
            text="This keyboard has full-size buttons (resize_keyboard=False):",
            keyboard=keyboard,
            resize_keyboard=False,
        )

    app.register_command(SimpleCommand(
        command="/noresize",
        description="Show keyboard without resize (tall buttons)",
        message_builder=show_noresize_keyboard,
    ))

    # Command: Remove the reply keyboard
    async def remove_keyboard() -> TelegramRemoveReplyKeyboardMessage:
        """Remove the persistent reply keyboard."""
        return TelegramRemoveReplyKeyboardMessage(
            text="Reply keyboard has been removed.",
        )

    app.register_command(SimpleCommand(
        command="/remove",
        description="Remove the reply keyboard",
        message_builder=remove_keyboard,
    ))

    # Command: Remove keyboard with custom message
    async def remove_keyboard_custom() -> TelegramRemoveReplyKeyboardMessage:
        """Remove keyboard with a custom message."""
        return TelegramRemoveReplyKeyboardMessage(
            text="<b>Keyboard removed!</b>\n\nYou can now type freely.",
        )

    app.register_command(SimpleCommand(
        command="/remove_custom",
        description="Remove keyboard with custom HTML message",
        message_builder=remove_keyboard_custom,
    ))

    # Command: Show keyboard with HTML formatting
    async def show_html_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a keyboard with HTML-formatted text."""
        keyboard = [
            ["✅ Accept", "❌ Decline"],
            ["ℹ️ Info"],
        ]
        return TelegramReplyKeyboardMessage(
            text="<b>Choose an action:</b>\n\n<i>Select from the options below</i>",
            keyboard=keyboard,
        )

    app.register_command(SimpleCommand(
        command="/html",
        description="Show keyboard with HTML-formatted text",
        message_builder=show_html_keyboard,
    ))

    # Command: Show keyboard with combined parameters
    async def show_combined_keyboard() -> TelegramReplyKeyboardMessage:
        """Display a keyboard with both one_time_keyboard and resize_keyboard=False."""
        keyboard = [
            ["Option 1"],
            ["Option 2"],
        ]
        return TelegramReplyKeyboardMessage(
            text="This keyboard combines one_time_keyboard=True and resize_keyboard=False:",
            keyboard=keyboard,
            one_time_keyboard=True,
            resize_keyboard=False,
        )

    app.register_command(SimpleCommand(
        command="/combined",
        description="Show keyboard with combined parameters (one-time + no-resize)",
        message_builder=show_combined_keyboard,
    ))

    # Info command
    info_text = (
        "<b>Reply Keyboard Bot</b>\n\n"
        "Tests TelegramReplyKeyboardMessage and TelegramRemoveReplyKeyboardMessage:\n"
        "• Simple 2x2 keyboard layout\n"
        "• Single row keyboard\n"
        "• Single column keyboard\n"
        "• one_time_keyboard parameter\n"
        "• resize_keyboard parameter\n"
        "• Combined parameters (one-time + no-resize)\n"
        "• HTML formatting in message text\n"
        "• Removing reply keyboard\n"
        "• Custom removal messages"
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
            f"⌨️ <b>Reply Keyboard Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("send_startup_and_run: starting")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
