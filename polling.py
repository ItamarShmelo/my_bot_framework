"""Telegram update polling utilities.

This module provides:
- get_next_update_id(): Get the next update ID to poll from
- set_next_update_id(): Set the next update ID to poll from
- flush_pending_updates(): Clear pending updates on startup
- poll_updates(): Poll for Telegram updates
- get_chat_id_from_update(): Extract chat_id from an update
- UpdatePollerMixin: Mixin class for update polling with Template Method Pattern
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple, cast

from telegram import Bot, Update
from telegram.error import NetworkError, RetryAfter, TimedOut

from .accessors import get_app, get_bot, get_chat_id, get_logger
from .retry_utilities import (
    DEFAULT_RETRY_MAX_ATTEMPTS,
    RetryAfterExceededError,
    run_with_transient_retry,
)


# Module-level state for tracking Telegram update offset
_next_update_id: int = 0

# Timeout for Telegram get_updates calls (used by both poll and flush).
GET_UPDATES_TIMEOUT_SECONDS: int = 5

# Log first poll failure, then every Nth failure.
POLL_FAILURE_LOG_EVERY_N: int = 5

# Tracks consecutive receive-side failures to emit recovery transition logs.
_poll_consecutive_failures: int = 0

# Delay before retrying after unexpected poll_updates exception.
POLL_EXCEPTION_RETRY_DELAY_SECONDS: int = 2


def get_next_update_id() -> int:
    """Get the next update ID to poll from.

    Returns:
        The next update ID to use for polling.
    """
    return _next_update_id


def set_next_update_id(value: int) -> None:
    """Set the next update ID to poll from.

    Args:
        value: The next update ID to use for polling.
    """
    global _next_update_id
    _next_update_id = value


async def flush_pending_updates(
    bot: Bot,
    timeout: int = GET_UPDATES_TIMEOUT_SECONDS,
) -> None:
    """Flush all pending updates and set the next update ID.

    Call this when the bot starts to ignore old messages.

    Args:
        bot: The Telegram Bot instance.
        timeout: get_updates timeout for startup flush. Defaults to
            GET_UPDATES_TIMEOUT_SECONDS.
    """
    logger: logging.Logger = get_logger()
    logger.debug(
        "flush_pending_updates: fetching_pending_updates offset=-1 timeout=%d max_attempts=%d",
        timeout,
        DEFAULT_RETRY_MAX_ATTEMPTS,
    )

    try:
        updates = await run_with_transient_retry(
            lambda: bot.get_updates(offset=-1, timeout=timeout),
        )
    except RetryAfterExceededError:
        logger.error(
            "flush_pending_updates: retry_after_exceeded offset=-1 timeout=%d max_attempts=%d",
            timeout,
            DEFAULT_RETRY_MAX_ATTEMPTS,
            exc_info=True,
        )
        raise
    except (TimedOut, NetworkError, RetryAfter):
        logger.error(
            "flush_pending_updates: transient_failures_exhausted offset=-1 timeout=%d max_attempts=%d",
            timeout,
            DEFAULT_RETRY_MAX_ATTEMPTS,
            exc_info=True,
        )
        raise

    if updates:
        next_id: int = updates[-1].update_id + 1
        set_next_update_id(next_id)
        logger.info("flush_pending_updates: cleared=%d next_id=%d", len(updates), next_id)
    else:
        set_next_update_id(0)
        logger.info("flush_pending_updates: no_pending_updates")


def _log_poll_failure(logger: logging.Logger) -> None:
    """Log poll failures with throttling to reduce noisy logs during outages.

    Args:
        logger: Logger instance for emitting messages.
    """
    global _poll_consecutive_failures
    _poll_consecutive_failures += 1
    should_log: bool = (
        _poll_consecutive_failures == 1
        or _poll_consecutive_failures % POLL_FAILURE_LOG_EVERY_N == 0
    )
    if should_log:
        logger.warning(
            "_log_poll_failure: poll_receive_failure consecutive=%d log_every_n=%d",
            _poll_consecutive_failures,
            POLL_FAILURE_LOG_EVERY_N,
            exc_info=True,
        )


def _log_poll_recovery(logger: logging.Logger) -> None:
    """Log transition from failure streak back to healthy polling.

    Args:
        logger: Logger instance for emitting messages.
    """
    global _poll_consecutive_failures
    if _poll_consecutive_failures > 0:
        logger.warning(
            "_log_poll_recovery: poll_receive_recovered consecutive_failures=%d",
            _poll_consecutive_failures,
        )
        _poll_consecutive_failures = 0


async def poll_updates(bot: Bot, timeout: int = GET_UPDATES_TIMEOUT_SECONDS) -> List[Update]:
    """Poll for updates and update the global next_update_id.

    Catches transient Telegram network errors (TimedOut, NetworkError)
    so the polling loop can continue without crashing.

    Args:
        bot: The Telegram Bot instance.
        timeout: Long-polling timeout in seconds.

    Returns:
        List of received updates, or empty list on transient error.
    """
    logger: logging.Logger = get_logger()
    logger.debug("poll_updates: polling offset=%d timeout=%d", get_next_update_id(), timeout)

    try:
        updates_tuple: Tuple[Update, ...] = await run_with_transient_retry(
            lambda: bot.get_updates(
                offset=get_next_update_id(),
                timeout=timeout,
                allowed_updates=["message", "callback_query"],
            ),
        )
        _log_poll_recovery(logger)
    except RetryAfterExceededError:
        _log_poll_failure(logger)
        logger.warning(
            "poll_updates: retry_after_exceeded offset=%d timeout=%d",
            get_next_update_id(),
            timeout,
            exc_info=True,
        )
        return []
    except (TimedOut, NetworkError, RetryAfter):
        _log_poll_failure(logger)
        logger.warning(
            "poll_updates: transient_failures_exhausted offset=%d timeout=%d max_attempts=%d",
            get_next_update_id(),
            timeout,
            DEFAULT_RETRY_MAX_ATTEMPTS,
            exc_info=True,
        )
        return []

    updates: List[Update] = list(updates_tuple)
    if updates:
        next_update_id: int = max(updates, key=lambda u: u.update_id).update_id + 1
        set_next_update_id(next_update_id)
        logger.debug("poll_updates: received count=%d next_id=%d", len(updates), next_update_id)
    else:
        logger.debug("poll_updates: no_updates_received offset=%d", get_next_update_id())
    return updates


def get_chat_id_from_update(update: Update) -> Optional[int]:
    """Extract chat_id from update.

    Args:
        update: The Telegram update to extract chat_id from.

    Returns:
        The chat ID if found in the update, None otherwise.
    """
    if update.callback_query and update.callback_query.message:
        message = update.callback_query.message
        if message and hasattr(message, "chat_id"):
            return cast(int, message.chat_id)
    if update.message and hasattr(update.message, "chat_id"):
        return update.message.chat_id
    return None


class UpdatePollerMixin(ABC):
    """Mixin providing Telegram update polling with Template Method Pattern.

    Text updates matching /terminate are intercepted globally before routing.
    Subclasses implement:
    - should_stop_polling(): when to exit the poll loop
    - handle_callback_update(update): process callback queries
    - handle_text_update(update): process text messages

    Uses singleton accessors (get_bot, get_chat_id, get_logger, get_app) for dependencies.
    """

    @abstractmethod
    def should_stop_polling(self) -> bool:
        """Return True when polling should stop."""
        ...

    @abstractmethod
    async def handle_callback_update(self, update: Update) -> None:
        """Handle a callback query update."""
        ...

    @abstractmethod
    async def handle_text_update(self, update: Update) -> None:
        """Handle a text message update."""
        ...

    async def poll(self) -> Any:
        """Template method: poll updates and route to handlers.

        Send-side errors are handled inside ``TelegramMessage.send()``.
        The safety net around ``poll_updates()`` catches truly unexpected
        receive-side errors so the polling loop keeps running.

        Returns:
            Subclass-specific result from _get_poll_result().
        """
        bot: Bot = get_bot()
        chat_id: str = get_chat_id()
        logger: logging.Logger = get_logger()

        logger.info("UpdatePollerMixin.poll: started")
        while not self.should_stop_polling():
            try:
                updates: List[Update] = await poll_updates(bot)
            except Exception:
                logger.error(
                    "UpdatePollerMixin.poll: poll_updates_failed retry_delay_seconds=%d",
                    POLL_EXCEPTION_RETRY_DELAY_SECONDS,
                    exc_info=True,
                )
                await asyncio.sleep(POLL_EXCEPTION_RETRY_DELAY_SECONDS)
                continue

            for update in updates:
                update_chat_id: Optional[int] = get_chat_id_from_update(update)
                if update_chat_id is None or str(update_chat_id) != chat_id:
                    logger.debug(
                        "UpdatePollerMixin.poll: filtered update wrong_chat=%s expected=%s",
                        update_chat_id,
                        chat_id,
                    )
                    continue

                if update.callback_query:
                    await self.handle_callback_update(update)
                elif update.message and update.message.text:
                    if await self._check_terminate(update, logger):
                        return self._get_poll_result()
                    await self.handle_text_update(update)

        logger.info("UpdatePollerMixin.poll: stopped")
        return self._get_poll_result()

    async def _check_terminate(self, update: Update, logger: logging.Logger) -> bool:
        """Check if the update is a /terminate command and handle it.

        Returns:
            True if the bot was terminated, False otherwise.
        """
        if update.message is None or update.message.text is None:
            return False
        if update.message.text.strip() != "/terminate":
            return False
        logger.info(
            "UpdatePollerMixin._check_terminate: terminate_received update_id=%d",
            update.update_id,
        )
        set_next_update_id(update.update_id + 1)
        await get_app().terminate()
        return True

    def _get_poll_result(self) -> Any:
        """Override to customize the result returned by poll()."""
        return None
