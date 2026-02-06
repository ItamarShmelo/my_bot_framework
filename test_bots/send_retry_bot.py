"""Bot that monkey-patches Telegram send methods to inject failures.

Tests retry logic in TelegramMessage.send() by injecting:
- TimedOut errors (with exponential backoff)
- NetworkError errors (with exponential backoff)
- RetryAfter errors (respecting retry_after duration)
- Exhausting retries after SEND_MAX_RETRIES attempts

The bot should demonstrate that:
- Transient errors (TimedOut, NetworkError) are retried with exponential backoff
- RetryAfter errors wait the specified duration before retrying
- Messages eventually succeed after retries
- Retries are exhausted after SEND_MAX_RETRIES attempts
"""

import asyncio
import logging
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from telegram import Bot, Message
from telegram.error import NetworkError, RetryAfter, TimedOut

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    SEND_MAX_RETRIES,
    SEND_RETRY_BASE_DELAY_SECONDS,
    TelegramTextMessage,
    TelegramImageMessage,
    TelegramDocumentMessage,
    TelegramOptionsMessage,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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


# Counters for tracking injected errors (shared across all patched methods)
_call_counts: dict[str, int] = {}


def create_patched_send_method(
    original_method: Callable,
    method_name: str,
    logger: logging.Logger,
) -> Callable:
    """Create a patched send method that injects failures.

    Args:
        original_method: The original Telegram API method to wrap.
        method_name: Name of the method (for logging).
        logger: Logger for reporting injected errors.

    Returns:
        Patched method that injects failures on a schedule.
    """
    async def patched_method(*args: Any, **kwargs: Any) -> Message:
        """Wrapper that injects failures on a fixed schedule."""
        _call_counts[method_name] = _call_counts.get(method_name, 0) + 1
        count = _call_counts[method_name]
        logger.debug(f"patched_{method_name}: call_count={count}")

        # Test 1: TimedOut on first attempt, succeed on second
        if count == 1:
            logger.warning(
                f"patched_{method_name}: injected_timed_out call_count={count}"
            )
            raise TimedOut()

        # Test 2: NetworkError on first attempt, succeed on second
        if count == 2:
            logger.warning(
                f"patched_{method_name}: injected_network_error call_count={count}"
            )
            raise NetworkError("Injected network error for testing")

        # Test 3: RetryAfter with 2 second wait
        if count == 3:
            logger.warning(
                f"patched_{method_name}: injected_retry_after call_count={count} retry_after=2s"
            )
            raise RetryAfter(timedelta(seconds=2))

        # Test 4: Multiple TimedOut errors (test exponential backoff)
        # Fail first 2 attempts (attempts 0 and 1), succeed on 3rd (attempt 2)
        if count in [4, 5]:
            logger.warning(
                f"patched_{method_name}: injected_timed_out call_count={count} (multiple retries)"
            )
            raise TimedOut()

        # Test 5: Exhaust retries (fail all SEND_MAX_RETRIES attempts)
        # This should log an error and return (swallow the error)
        # Need to fail on attempts 0, 1, 2 (3 total attempts)
        if 7 <= count <= 7 + SEND_MAX_RETRIES - 1:
            logger.warning(
                f"patched_{method_name}: injected_timed_out call_count={count} (exhausting retries)"
            )
            raise TimedOut()

        # All other calls succeed
        logger.debug(f"patched_{method_name}: calling original method call_count={count}")
        return await original_method(*args, **kwargs)

    return patched_method


def patch_send_methods(bot: Bot, logger: logging.Logger) -> None:
    """Monkey-patch bot send methods to inject intermittent failures.

    Patches:
    - bot.send_message
    - bot.send_photo
    - bot.send_document

    Args:
        bot: The Telegram Bot instance to patch.
        logger: Logger for reporting injected errors.
    """
    # Reset counters
    _call_counts.clear()

    # Patch send_message (Bot uses __slots__, so we must use object.__setattr__)
    original_send_message = bot.send_message
    object.__setattr__(bot, "send_message", create_patched_send_method(
        original_send_message,
        "send_message",
        logger,
    ))

    # Patch send_photo
    original_send_photo = bot.send_photo
    object.__setattr__(bot, "send_photo", create_patched_send_method(
        original_send_photo,
        "send_photo",
        logger,
    ))

    # Patch send_document
    original_send_document = bot.send_document
    object.__setattr__(bot, "send_document", create_patched_send_method(
        original_send_document,
        "send_document",
        logger,
    ))

    logger.info("patch_send_methods: monkey_patched send_methods_patched=True")


def main() -> None:
    """Run the send retry test bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("send_retry_bot")
    logger.info("main: starting send_retry_bot")

    token, chat_id = get_credentials()

    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Monkey-patch send methods BEFORE registering commands
    patch_send_methods(app.bot, logger)

    # Register test commands
    app.register_command(SimpleCommand(
        command="/test_timedout",
        description="Test TimedOut retry (should succeed after 1 retry)",
        message_builder=lambda: "✅ Test 1: TimedOut retry succeeded!",
    ))

    app.register_command(SimpleCommand(
        command="/test_network_error",
        description="Test NetworkError retry (should succeed after 1 retry)",
        message_builder=lambda: "✅ Test 2: NetworkError retry succeeded!",
    ))

    app.register_command(SimpleCommand(
        command="/test_retry_after",
        description="Test RetryAfter handling (waits 2 seconds, then succeeds)",
        message_builder=lambda: "✅ Test 3: RetryAfter handling succeeded!",
    ))

    app.register_command(SimpleCommand(
        command="/test_multiple_retries",
        description="Test multiple retries with exponential backoff (fails 2x, succeeds on 3rd)",
        message_builder=lambda: "✅ Test 4: Multiple retries with exponential backoff succeeded!",
    ))

    app.register_command(SimpleCommand(
        command="/test_exhaust_retries",
        description=f"Test exhausting retries (fails all {SEND_MAX_RETRIES} attempts, error logged)",
        message_builder=lambda: (
            f"❌ Test 5: This should fail after {SEND_MAX_RETRIES} attempts. "
            f"Check logs for 'all_retries_exhausted' message. "
            f"Note: This message may not be sent if retries are exhausted."
        ),
    ))

    app.register_command(SimpleCommand(
        command="/test_image",
        description="Test retry with TelegramImageMessage",
        message_builder=lambda: TelegramImageMessage(
            image_path=Path(__file__).parent / "test_image.png",
            caption="Test image with retry logic",
        ) if (Path(__file__).parent / "test_image.png").exists() else "⚠️ test_image.png not found",
    ))

    app.register_command(SimpleCommand(
        command="/test_document",
        description="Test retry with TelegramDocumentMessage",
        message_builder=lambda: TelegramDocumentMessage(
            file_path=Path(__file__).parent / "test_document.txt",
            caption="Test document with retry logic",
        ) if (Path(__file__).parent / "test_document.txt").exists() else "⚠️ test_document.txt not found",
    ))

    app.register_command(SimpleCommand(
        command="/test_options",
        description="Test retry with TelegramOptionsMessage",
        message_builder=lambda: TelegramOptionsMessage(
            text="Test options message with retry logic",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Button 1", callback_data="btn1")],
                [InlineKeyboardButton("Button 2", callback_data="btn2")],
            ]),
        ),
    ))

    def stats_message() -> str:
        """Build a stats message showing send call counts."""
        send_message_count = _call_counts.get("send_message", 0)
        send_photo_count = _call_counts.get("send_photo", 0)
        send_document_count = _call_counts.get("send_document", 0)
        return (
            "<b>Send Retry Test Stats</b>\n\n"
            f"send_message calls: {send_message_count}\n"
            f"send_photo calls: {send_photo_count}\n"
            f"send_document calls: {send_document_count}\n\n"
            "<b>Test Schedule:</b>\n"
            "• Call 1: TimedOut (succeeds on retry)\n"
            "• Call 2: NetworkError (succeeds on retry)\n"
            "• Call 3: RetryAfter 2s (succeeds after wait)\n"
            "• Calls 4-5: Multiple TimedOut (fails 2x, succeeds on 3rd attempt)\n"
            f"• Calls 7-{7 + SEND_MAX_RETRIES - 1}: Exhaust retries (all {SEND_MAX_RETRIES} attempts fail)\n\n"
            f"<b>Retry Configuration:</b>\n"
            f"• SEND_MAX_RETRIES: {SEND_MAX_RETRIES}\n"
            f"• SEND_RETRY_BASE_DELAY_SECONDS: {SEND_RETRY_BASE_DELAY_SECONDS}"
        )

    app.register_command(SimpleCommand(
        command="/stats",
        description="Show send retry test statistics",
        message_builder=stats_message,
    ))

    info_text = (
        "<b>Send Retry Bot</b>\n\n"
        "Tests retry logic in TelegramMessage.send():\n"
        "• <code>TimedOut</code> errors with exponential backoff\n"
        "• <code>NetworkError</code> errors with exponential backoff\n"
        "• <code>RetryAfter</code> errors (respects retry_after duration)\n"
        "• Exhausting retries after SEND_MAX_RETRIES attempts\n\n"
        "Use /test_* commands to trigger different retry scenarios.\n"
        "Use /stats to see call counts and configuration."
    )

    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    async def send_startup_and_run() -> None:
        """Send startup message and run the bot."""
        logger.debug("send_startup_and_run: sending startup message")
        await app.send_messages(
            f"{info_text}\n\n"
            "💡 Type /commands to see all available commands.\n"
            "💡 Start with /test_timedout to see retry logic in action."
        )
        logger.info("send_startup_and_run: startup_message_sent retry_testing_active=True")
        logger.info("send_startup_and_run: starting bot application")
        await app.run()
        logger.info("send_startup_and_run: bot application stopped")

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
