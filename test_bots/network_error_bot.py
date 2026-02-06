"""Bot that monkey-patches get_updates to fail intermittently.

Tests exception safety of the polling layer by injecting:
- TimedOut errors (every 3rd poll cycle)
- NetworkError errors (every 5th poll cycle)
- Unexpected RuntimeError (every 11th poll cycle)

The bot should keep running despite these errors, demonstrating that:
- poll_updates() catches TimedOut and NetworkError gracefully
- UpdatePollerMixin.poll() safety net catches unexpected errors
- Normal polling resumes after transient failures
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Tuple

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from telegram import Bot, Update
from telegram.error import NetworkError, TimedOut

from my_bot_framework import BotApplication, SimpleCommand, TimeEvent


def get_credentials() -> Tuple[str, str]:
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
        logger = logging.getLogger("network_error_bot")
        logger.error(
            "get_credentials: missing_credential_files token_file_exists=%s chat_id_file_exists=%s",
            token_file.exists(),
            chat_id_file.exists(),
        )
        raise RuntimeError(
            "Missing credential files. Create .token and .chat_id files in test_bots directory."
        )

    token = token_file.read_text().strip()
    chat_id = chat_id_file.read_text().strip()

    if not token or not chat_id:
        logger = logging.getLogger("network_error_bot")
        logger.error(
            "get_credentials: empty_credential_files token_empty=%s chat_id_empty=%s",
            not token,
            not chat_id,
        )
        raise RuntimeError(
            "Empty credential files. Ensure .token and .chat_id contain valid values."
        )
    return token, chat_id


# Counters for tracking injected errors
_poll_call_count: int = 0
_timed_out_count: int = 0
_network_error_count: int = 0
_unexpected_error_count: int = 0


def patch_get_updates(bot: Bot, logger: logging.Logger) -> None:
    """Monkey-patch bot.get_updates to inject intermittent failures.

    Failure schedule:
    - Every 3rd call: raises TimedOut
    - Every 5th call (that isn't already a 3rd): raises NetworkError
    - Every 11th call (that isn't already a 3rd or 5th): raises RuntimeError

    All other calls pass through to the real get_updates.

    Args:
        bot: The Telegram Bot instance to patch.
        logger: Logger for reporting injected errors.
    """
    global _poll_call_count
    logger.debug("patch_get_updates: resetting poll_call_count")
    _poll_call_count = 0

    original_get_updates = bot.get_updates

    async def patched_get_updates(
        *args: Any,
        **kwargs: Any,
    ) -> Tuple[Update, ...]:
        """Wrapper that injects failures on a fixed schedule."""
        global _poll_call_count, _timed_out_count, _network_error_count, _unexpected_error_count
        _poll_call_count += 1
        count = _poll_call_count
        logger.debug("patched_get_updates: poll_cycle=%d", count)

        if count % 3 == 0:
            _timed_out_count += 1
            logger.warning(
                "patched_get_updates: injected_timed_out poll_cycle=%d total_injected=%d",
                count,
                _timed_out_count,
            )
            raise TimedOut()

        if count % 5 == 0:
            _network_error_count += 1
            logger.warning(
                "patched_get_updates: injected_network_error poll_cycle=%d total_injected=%d",
                count,
                _network_error_count,
            )
            raise NetworkError("Injected network error for testing")

        if count % 11 == 0:
            _unexpected_error_count += 1
            logger.warning(
                "patched_get_updates: injected_runtime_error poll_cycle=%d total_injected=%d",
                count,
                _unexpected_error_count,
            )
            raise RuntimeError("Injected unexpected error for testing")

        logger.debug("patched_get_updates: calling original_get_updates poll_cycle=%d", count)
        result = await original_get_updates(*args, **kwargs)
        logger.debug("patched_get_updates: original_get_updates returned updates_count=%d poll_cycle=%d", len(result), count)
        return result

    # Bot.__setattr__ blocks public attribute assignment; bypass it.
    object.__setattr__(bot, "get_updates", patched_get_updates)
    logger.info("patch_get_updates: monkey_patched bot_get_updates_patched=True")


def main() -> None:
    """Run the network error test bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("network_error_bot")
    logger.info("main: starting network_error_bot")

    token, chat_id = get_credentials()

    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Monkey-patch get_updates BEFORE the bot starts polling
    patch_get_updates(app.bot, logger)

    # Register a command to show injection stats
    def stats_message() -> str:
        """Build a stats message showing injected error counts."""
        return (
            "<b>Error Injection Stats</b>\n\n"
            f"Total poll cycles: {_poll_call_count}\n"
            f"TimedOut injected: {_timed_out_count}\n"
            f"NetworkError injected: {_network_error_count}\n"
            f"RuntimeError injected: {_unexpected_error_count}\n\n"
            "If you can read this, the bot survived all injected errors."
        )

    app.register_command(SimpleCommand(
        command="/stats",
        description="Show error injection statistics",
        message_builder=stats_message,
    ))

    app.register_command(SimpleCommand(
        command="/hello",
        description="Say hello (proves bot is responsive)",
        message_builder=lambda: "Hello! The bot is still running despite injected errors.",
    ))

    info_text = (
        "<b>Network Error Bot</b>\n\n"
        "Tests exception safety by injecting:\n"
        "• <code>TimedOut</code> every 3rd poll cycle\n"
        "• <code>NetworkError</code> every 5th poll cycle\n"
        "• <code>RuntimeError</code> every 11th poll cycle\n\n"
        "The bot should keep running despite these errors.\n"
        "Use /stats to see injection counts."
    )

    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    # Periodic heartbeat to prove the bot is alive
    app.register_event(TimeEvent(
        event_name="heartbeat",
        interval_hours=5.0 / 60.0,  # 5 minutes
        message_builder=lambda: f"Heartbeat (poll cycle {_poll_call_count}): Bot is alive!",
        fire_on_first_check=True,
    ))

    async def send_startup_and_run() -> None:
        """Send startup message and run the bot."""
        logger.debug("send_startup_and_run: sending startup message")
        await app.send_messages(
            f"{info_text}\n\n"
            "💡 Type /commands to see all available commands."
        )
        logger.info("send_startup_and_run: startup_message_sent error_injection_active=True")
        logger.info("send_startup_and_run: starting bot application")
        await app.run()
        logger.info("send_startup_and_run: bot application stopped")

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
