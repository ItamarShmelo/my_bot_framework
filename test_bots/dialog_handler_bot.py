"""Dialog Handler bot testing the new DialogHandler and cancellation features.

Tests:
- DialogHandler: Wrap dialogs with on_complete callback
- CANCELLED sentinel: Unambiguous cancellation detection
- is_cancelled(): Helper function for checking cancellation
- Nested DialogHandlers: Multiple handlers in a chain
- DialogResult: Standardized result structure from build_result()
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    DialogCommand,
    SimpleCommand,
    # Dialog types
    ChoiceDialog,
    UserInputDialog,
    ConfirmDialog,
    SequenceDialog,
    # New features
    DialogHandler,
    CANCELLED,
    is_cancelled,
    get_logger,
    get_bot,
    get_chat_id,
    TelegramTextMessage,
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


# =============================================================================
# DIALOG DEFINITIONS
# =============================================================================

# /handler - Tests basic DialogHandler with on_complete callback
async def on_feedback_complete(result):
    """Callback when feedback dialog completes - sends Telegram message."""
    logger = get_logger()
    bot = get_bot()
    chat_id = get_chat_id()
    
    if is_cancelled(result):
        logger.info("feedback_handler: User cancelled")
        msg = TelegramTextMessage("Feedback cancelled.")
    else:
        logger.info("feedback_handler: Got feedback result=%s", result)
        msg = TelegramTextMessage(f"Thank you for your feedback: {result}")
    
    await msg.send(bot, chat_id, logger)

feedback_dialog = DialogHandler(
    ChoiceDialog("How was your experience?", [
        ("Excellent", "excellent"),
        ("Good", "good"),
        ("Fair", "fair"),
        ("Poor", "poor"),
    ]),
    on_complete=on_feedback_complete,
)


# /sequence_handler - Tests DialogHandler wrapping a SequenceDialog
async def on_survey_complete(result):
    """Callback when survey dialog completes - sends Telegram message."""
    logger = get_logger()
    bot = get_bot()
    chat_id = get_chat_id()
    
    if is_cancelled(result):
        logger.info("survey_handler: User cancelled the survey")
        msg = TelegramTextMessage("Survey cancelled.")
    else:
        logger.info("survey_handler: Survey complete result=%s", result)
        # Build summary message
        if isinstance(result, dict):
            lines = ["📊 Survey Complete!", ""]
            for key, value in result.items():
                logger.info("  %s = %s", key, value)
                lines.append(f"• {key}: {value}")
            msg = TelegramTextMessage("\n".join(lines))
        else:
            msg = TelegramTextMessage(f"Survey complete: {result}")
    
    await msg.send(bot, chat_id, logger)

survey_dialog = DialogHandler(
    SequenceDialog([
        ("name", UserInputDialog("What is your name?")),
        ("rating", ChoiceDialog("Rate our service:", [
            ("5 Stars", "5"),
            ("4 Stars", "4"),
            ("3 Stars", "3"),
            ("2 Stars", "2"),
            ("1 Star", "1"),
        ])),
        ("recommend", ConfirmDialog("Would you recommend us?")),
    ]),
    on_complete=on_survey_complete,
)


# /async_handler - Tests DialogHandler with async on_complete callback
async def on_order_complete(result):
    """Async callback when order dialog completes - sends Telegram message."""
    logger = get_logger()
    bot = get_bot()
    chat_id = get_chat_id()
    
    if is_cancelled(result):
        logger.info("order_handler: Order cancelled")
        msg = TelegramTextMessage("Order cancelled.")
        await msg.send(bot, chat_id, logger)
        return
    
    logger.info("order_handler: Processing order...")
    # Simulate async processing
    await asyncio.sleep(1)
    logger.info("order_handler: Order processed! result=%s", result)
    
    # Build order confirmation message
    if isinstance(result, dict):
        lines = ["🛒 Order Confirmed!", ""]
        for key, value in result.items():
            lines.append(f"• {key}: {value}")
        msg = TelegramTextMessage("\n".join(lines))
    else:
        msg = TelegramTextMessage(f"Order processed: {result}")
    
    await msg.send(bot, chat_id, logger)

order_dialog = DialogHandler(
    SequenceDialog([
        ("product", ChoiceDialog("Select product:", [
            ("Widget", "widget"),
            ("Gadget", "gadget"),
            ("Gizmo", "gizmo"),
        ])),
        ("quantity", UserInputDialog("Enter quantity (1-10):")),
        ("confirm", ConfirmDialog("Confirm order?")),
    ]),
    on_complete=on_order_complete,
)


# /nested_handler - Tests nested DialogHandlers
async def on_inner_complete(result):
    """Callback for inner dialog - sends Telegram message."""
    logger = get_logger()
    bot = get_bot()
    chat_id = get_chat_id()
    
    logger.info("inner_handler: Got result=%s", result)
    
    if is_cancelled(result):
        msg = TelegramTextMessage("Inner handler: Cancelled")
    else:
        msg = TelegramTextMessage(f"Inner handler received: {result}")
    
    await msg.send(bot, chat_id, logger)

async def on_outer_complete(result):
    """Callback for outer dialog - sends Telegram message."""
    logger = get_logger()
    bot = get_bot()
    chat_id = get_chat_id()
    
    logger.info("outer_handler: Final result=%s", result)
    
    if is_cancelled(result):
        msg = TelegramTextMessage("Outer handler: Cancelled")
    else:
        msg = TelegramTextMessage(f"🎨 Outer handler final result: {result}")
    
    await msg.send(bot, chat_id, logger)

nested_dialog = DialogHandler(
    DialogHandler(
        ChoiceDialog("Pick a color:", [
            ("Red", "red"),
            ("Green", "green"),
            ("Blue", "blue"),
        ]),
        on_complete=on_inner_complete,
    ),
    on_complete=on_outer_complete,
)


# /cancel_test - Tests cancellation handling
async def on_cancel_test_complete(result):
    """Callback demonstrating CANCELLED sentinel usage - sends Telegram message."""
    logger = get_logger()
    bot = get_bot()
    chat_id = get_chat_id()
    
    # Using the is_cancelled() helper
    if is_cancelled(result):
        logger.info("cancel_test: Dialog was cancelled (detected via is_cancelled)")
        msg = TelegramTextMessage("❌ Dialog was cancelled!")
        await msg.send(bot, chat_id, logger)
        return
    
    logger.info("cancel_test: Dialog completed with result=%s", result)
    msg = TelegramTextMessage(f"✅ Dialog completed with: {result}")
    await msg.send(bot, chat_id, logger)

cancel_test_dialog = DialogHandler(
    ConfirmDialog(
        "Try pressing Cancel to see cancellation handling.",
        include_cancel=True,
    ),
    on_complete=on_cancel_test_complete,
)


def main():
    """Run the dialog handler test bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("dialog_handler_bot")

    token, chat_id = get_credentials()

    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Register commands
    app.register_command(DialogCommand(
        "/handler",
        "Test basic DialogHandler with on_complete callback",
        feedback_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/sequence_handler",
        "Test DialogHandler wrapping SequenceDialog",
        survey_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/async_handler",
        "Test DialogHandler with async on_complete callback",
        order_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/nested_handler",
        "Test nested DialogHandlers",
        nested_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/cancel_test",
        "Test cancellation handling with CANCELLED sentinel",
        cancel_test_dialog,
    ))

    # Register info command
    info_text = (
        "<b>Dialog Handler Bot</b>\n\n"
        "Tests DialogHandler and cancellation features:\n"
        "• <code>DialogHandler</code> - Wrap dialogs with on_complete callback\n"
        "• <code>CANCELLED</code> sentinel - Unambiguous cancellation detection\n"
        "• <code>is_cancelled()</code> - Helper function for checking cancellation\n"
        "• Nested DialogHandlers - Multiple handlers in a chain\n"
        "• <code>DialogResult</code> - Standardized result structure\n\n"
        "<b>Commands:</b>\n"
        "/handler - Basic DialogHandler test\n"
        "/sequence_handler - DialogHandler with SequenceDialog\n"
        "/async_handler - DialogHandler with async callback\n"
        "/nested_handler - Nested DialogHandlers\n"
        "/cancel_test - Cancellation handling demonstration"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))
    
    # Send startup message and run
    async def send_startup_and_run():
        startup_msg = TelegramTextMessage(
            f"🤖 <b>Dialog Handler Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        await startup_msg.send(app.bot, app.chat_id, logger)
        logger.info("Starting dialog_handler_bot...")
        await app.run()
    
    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
