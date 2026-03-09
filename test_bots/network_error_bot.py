"""Bot that monkey-patches get_updates to fail intermittently and in bursts.

Tests exception safety and retry/recovery behavior by injecting:
- Initial burst of 3 failures (tests startup flush retry with backoff)
- TimedOut errors (every 3rd poll cycle)
- NetworkError errors (every 5th poll cycle)
- Unexpected RuntimeError (every 11th poll cycle)
- Configurable outage bursts via /outage5, /outage10, /recovery_test

The bot should keep running despite these errors, demonstrating that:
- Startup flush uses run_with_transient_retry (retries, backoff, then succeeds)
- poll_updates() retries TimedOut/NetworkError with backoff, returns [] when exhausted
- Recovery transition logs (_log_poll_recovery) after prolonged outages
- UpdatePollerMixin.poll() safety net catches unexpected errors
- Normal polling resumes after transient failures

Expected behavior by failure mode:
- Initial startup burst (first 3 get_updates calls): flush retries with backoff and bot still starts.
- TimedOut (intermittent): poll_updates retries transiently, then returns [] if exhausted; loop continues.
- NetworkError (intermittent): same as TimedOut (transient retry + non-fatal loop continuation).
- RuntimeError (unexpected): not handled by poll_updates retry; UpdatePollerMixin safety net logs and continues.
- Outage burst (/outage5, /outage10, /recovery_test): consecutive transient failures increase failure counters,
  then successful polling resets consecutive_failures and updates last_successful_cycle.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from telegram import Bot, Update
from telegram.error import NetworkError, TimedOut

from my_bot_framework import BotApplication, SimpleCommand, TimeEvent


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
_burst_remaining: int = 0
_consecutive_failures: int = 0
_max_consecutive_failures: int = 0
_last_successful_cycle: int = 0


def _record_failure() -> None:
    """Track failure streak statistics."""
    global _consecutive_failures, _max_consecutive_failures
    _consecutive_failures += 1
    _max_consecutive_failures = max(_max_consecutive_failures, _consecutive_failures)


def _record_success(poll_cycle: int) -> None:
    """Track successful poll and reset current failure streak.

    Args:
        poll_cycle: The poll cycle number for this successful call.
    """
    global _consecutive_failures, _last_successful_cycle
    _consecutive_failures = 0
    _last_successful_cycle = poll_cycle


def _set_outage_burst(cycles: int) -> None:
    """Configure the next N poll cycles to fail with NetworkError.

    Args:
        cycles: Number of consecutive poll cycles to inject NetworkError.
    """
    global _burst_remaining
    _burst_remaining = max(0, cycles)


def patch_get_updates(bot: Bot, logger: logging.Logger) -> None:
    """Monkey-patch bot.get_updates to inject intermittent failures.

    Failure schedule:
    - Every 3rd call: raises TimedOut
    - Every 5th call (that isn't already a 3rd): raises NetworkError
    - Every 11th call (that isn't already a 3rd or 5th): raises RuntimeError
    - Burst mode: raises NetworkError for N consecutive calls when burst is configured

    All other calls pass through to the real get_updates.

    Args:
        bot: The Telegram Bot instance to patch.
        logger: Logger for reporting injected errors.
    """
    global _poll_call_count, _consecutive_failures, _max_consecutive_failures, _last_successful_cycle, _burst_remaining
    logger.debug("patch_get_updates: resetting poll_call_count")
    _poll_call_count = 0
    _consecutive_failures = 0
    _max_consecutive_failures = 0
    _last_successful_cycle = 0
    _burst_remaining = 3  # First 3 get_updates fail -> tests startup flush retry

    original_get_updates = bot.get_updates

    async def patched_get_updates(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Update, ...]:
        """Wrapper that injects failures on a fixed schedule.

        Returns:
            Updates from the real get_updates when no failure is injected.
        """
        global _poll_call_count, _timed_out_count, _network_error_count, _unexpected_error_count, _burst_remaining
        _poll_call_count += 1
        count = _poll_call_count
        logger.debug("patched_get_updates: poll_cycle=%d", count)

        if _burst_remaining > 0:
            _burst_remaining -= 1
            _network_error_count += 1
            _record_failure()
            logger.warning(
                "patched_get_updates: injected_burst_network_error poll_cycle=%d remaining=%d total_injected=%d consecutive_failures=%d",
                count,
                _burst_remaining,
                _network_error_count,
                _consecutive_failures,
            )
            raise NetworkError("Injected burst network error for outage simulation")

        if count % 3 == 0:
            _timed_out_count += 1
            _record_failure()
            logger.warning(
                "patched_get_updates: injected_timed_out poll_cycle=%d total_injected=%d consecutive_failures=%d",
                count,
                _timed_out_count,
                _consecutive_failures,
            )
            raise TimedOut()

        if count % 5 == 0:
            _network_error_count += 1
            _record_failure()
            logger.warning(
                "patched_get_updates: injected_network_error poll_cycle=%d total_injected=%d consecutive_failures=%d",
                count,
                _network_error_count,
                _consecutive_failures,
            )
            raise NetworkError("Injected network error for testing")

        if count % 11 == 0:
            _unexpected_error_count += 1
            _record_failure()
            logger.warning(
                "patched_get_updates: injected_runtime_error poll_cycle=%d total_injected=%d consecutive_failures=%d",
                count,
                _unexpected_error_count,
                _consecutive_failures,
            )
            raise RuntimeError("Injected unexpected error for testing")

        logger.debug("patched_get_updates: calling original_get_updates poll_cycle=%d", count)
        result = await original_get_updates(*args, **kwargs)
        _record_success(count)
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
    logger.info("main: starting bot=network_error_bot")

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
        """Build a stats message showing injected error counts.

        Returns:
            HTML-formatted string with error injection statistics.
        """
        return (
            "<b>Error Injection Stats</b>\n\n"
            f"Total poll cycles: {_poll_call_count}\n"
            f"TimedOut injected: {_timed_out_count}\n"
            f"NetworkError injected: {_network_error_count}\n"
            f"RuntimeError injected: {_unexpected_error_count}\n\n"
            f"Outage burst remaining: {_burst_remaining}\n"
            f"Consecutive failures: {_consecutive_failures}\n"
            f"Max consecutive failures: {_max_consecutive_failures}\n"
            f"Last successful cycle: {_last_successful_cycle}\n\n"
            "If you can read this, the bot survived all injected errors."
        )

    def outage_burst_message(cycles: int) -> str:
        """Set outage burst cycles and return confirmation text.

        Args:
            cycles: Number of consecutive poll cycles to inject NetworkError.

        Returns:
            Confirmation message describing the configured burst.
        """
        _set_outage_burst(cycles)
        return (
            f"Configured outage burst: next {cycles} poll cycles will inject "
            f"NetworkError. Use /burst_status to monitor recovery."
        )

    def burst_status_message() -> str:
        """Show current outage/recovery transition state.

        Returns:
            HTML-formatted string with burst and recovery status.
        """
        return (
            "<b>Burst/Recovery Status</b>\n\n"
            f"Outage burst remaining: {_burst_remaining}\n"
            f"Consecutive failures: {_consecutive_failures}\n"
            f"Max consecutive failures: {_max_consecutive_failures}\n"
            f"Last successful cycle: {_last_successful_cycle}\n"
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
    app.register_command(SimpleCommand(
        command="/outage5",
        description="Inject 5 consecutive NetworkError poll failures.",
        message_builder=lambda: outage_burst_message(5),
    ))
    app.register_command(SimpleCommand(
        command="/outage10",
        description="Inject 10 consecutive NetworkError poll failures.",
        message_builder=lambda: outage_burst_message(10),
    ))
    app.register_command(SimpleCommand(
        command="/recovery_test",
        description="Inject a prolonged outage then observe recovery transition.",
        message_builder=lambda: outage_burst_message(7),
    ))
    app.register_command(SimpleCommand(
        command="/burst_status",
        description="Show outage burst and recovery-transition status.",
        message_builder=burst_status_message,
    ))

    info_text = (
        "<b>Network Error Bot</b>\n\n"
        "Tests exception safety and retry/recovery:\n"
        "• Startup flush retry (first 3 get_updates fail, then succeed)\n"
        "• <code>TimedOut</code> every 3rd poll cycle\n"
        "• <code>NetworkError</code> every 5th poll cycle\n"
        "• <code>RuntimeError</code> every 11th poll cycle\n"
        "• Outage bursts via /outage5, /outage10, /recovery_test\n\n"
        "Use /stats and /burst_status to observe recovery transitions."
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
