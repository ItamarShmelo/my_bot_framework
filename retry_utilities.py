"""Shared retry utilities for transient Telegram API errors."""

import asyncio
import logging
import random
from datetime import timedelta
from typing import Awaitable, Callable, TypeVar

from telegram.error import NetworkError, RetryAfter, TimedOut


T = TypeVar("T")
logger = logging.getLogger(__name__)

# Shared retry defaults used across send/poll/flush paths.
DEFAULT_RETRY_MAX_ATTEMPTS: int = 6
DEFAULT_RETRY_BASE_DELAY_SECONDS: float = 1.0
DEFAULT_RETRY_JITTER_MAX_SECONDS: float = 1.0
DEFAULT_RETRY_MAX_BACKOFF_SECONDS: float | None = None
DEFAULT_RETRY_AFTER_BUFFER_SECONDS: float | None = 1.0
DEFAULT_RETRY_AFTER_MAX_WAIT_SECONDS: float = 120.0


class RetryAfterExceededError(RuntimeError):
    """Raised when RetryAfter delay exceeds the configured max wait.

    Raised by run_with_transient_retry when Telegram returns a RetryAfter
    delay greater than retry_after_max_wait_seconds.
    """


def calculate_exponential_backoff_with_jitter(
    attempt: int,
    base_delay_seconds: float,
    jitter_max_seconds: float = 1.0,
    max_delay_seconds: float | None = None,
) -> float:
    """Calculate retry delay using exponential backoff with jitter.

    Args:
        attempt: Retry attempt number (1-based).
        base_delay_seconds: Base delay in seconds.
        jitter_max_seconds: Max random jitter added to the base backoff.
        max_delay_seconds: Optional max cap for the resulting delay.

    Returns:
        Delay in seconds for the given attempt.
    """
    delay_seconds: float = base_delay_seconds * (2 ** (attempt - 1))
    if jitter_max_seconds > 0:
        delay_seconds += random.uniform(0.0, jitter_max_seconds)
    if max_delay_seconds is not None:
        delay_seconds = min(delay_seconds, max_delay_seconds)
    return delay_seconds


def calculate_retry_after_wait_seconds(
    retry_after: float | int | timedelta,
    buffer_seconds: float | None = 0.0,
) -> float:
    """Normalize RetryAfter value to seconds with an optional buffer.

    Args:
        retry_after: Retry delay value from Telegram (numeric or timedelta).
        buffer_seconds: Additional seconds to wait as safety buffer. ``None``
            is treated as 0.0. Defaults to 0.0.

    Returns:
        Total wait in seconds.
    """
    retry_after_seconds: float = (
        retry_after.total_seconds()
        if isinstance(retry_after, timedelta)
        else float(retry_after)
    )
    return retry_after_seconds + (buffer_seconds if buffer_seconds is not None else 0.0)


async def run_with_transient_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int | None = DEFAULT_RETRY_MAX_ATTEMPTS,
    base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
    jitter_max_seconds: float = DEFAULT_RETRY_JITTER_MAX_SECONDS,
    max_backoff_seconds: float | None = DEFAULT_RETRY_MAX_BACKOFF_SECONDS,
    retry_after_buffer_seconds: float | None = DEFAULT_RETRY_AFTER_BUFFER_SECONDS,
    retry_after_max_wait_seconds: float | None = DEFAULT_RETRY_AFTER_MAX_WAIT_SECONDS,
    count_retry_after_as_attempt: bool = False,
    on_transient_retry: Callable[[Exception, int, float], None] | None = None,
    on_retry_after_retry: Callable[[RetryAfter, int, float], None] | None = None,
) -> T:
    """Run an async operation with retries for transient Telegram errors.

    Retries are handled for ``TimedOut``, ``NetworkError``, and ``RetryAfter``.
    Any other exception is re-raised immediately.

    Args:
        operation: Async callable to execute.
        max_attempts: Maximum attempts for transient errors. ``None`` means
            unlimited attempts. Defaults to ``DEFAULT_RETRY_MAX_ATTEMPTS``.
        base_delay_seconds: Base delay for exponential backoff.
        jitter_max_seconds: Max random jitter added to each backoff delay.
        max_backoff_seconds: Optional cap for backoff delays. ``None`` means
            no cap. Defaults to ``DEFAULT_RETRY_MAX_BACKOFF_SECONDS``.
        retry_after_buffer_seconds: Buffer added to RetryAfter delays.
            ``None`` means no buffer. Defaults to
            ``DEFAULT_RETRY_AFTER_BUFFER_SECONDS``.
        retry_after_max_wait_seconds: Optional max allowed RetryAfter delay.
            ``None`` means no limit. Defaults to
            ``DEFAULT_RETRY_AFTER_MAX_WAIT_SECONDS``.
        count_retry_after_as_attempt: Whether RetryAfter consumes an attempt.
        on_transient_retry: Optional callback invoked before sleeping for
            TimedOut/NetworkError retries with (exception, attempt, delay).
        on_retry_after_retry: Optional callback invoked before sleeping for
            RetryAfter retries with (exception, attempt, delay).

    Returns:
        The operation result.

    Raises:
        Exception: Re-raises non-transient exceptions immediately and re-raises
            transient exceptions once attempts are exhausted.
        RetryAfterExceededError: If RetryAfter delay exceeds
            ``retry_after_max_wait_seconds``.
    """
    attempt: int = 1

    while True:
        try:
            return await operation()
        except RetryAfter as exc:
            if (
                count_retry_after_as_attempt
                and max_attempts is not None
                and attempt >= max_attempts
            ):
                raise
            wait_seconds = calculate_retry_after_wait_seconds(
                exc.retry_after,
                buffer_seconds=retry_after_buffer_seconds,
            )
            if (
                retry_after_max_wait_seconds is not None
                and wait_seconds > retry_after_max_wait_seconds
            ):
                raise RetryAfterExceededError(
                    f"RetryAfter wait {wait_seconds:.1f}s exceeds allowed "
                    f"maximum {retry_after_max_wait_seconds:.1f}s"
                ) from exc
            if on_retry_after_retry is not None:
                on_retry_after_retry(exc, attempt, wait_seconds)
            else:
                buffer_seconds: float = (
                    retry_after_buffer_seconds
                    if retry_after_buffer_seconds is not None
                    else 0.0
                )
                logger.warning(
                    "run_with_transient_retry: retry_after_waiting wait_seconds=%.1f buffer_seconds=%.1f attempt=%d/%s",
                    wait_seconds,
                    buffer_seconds,
                    attempt,
                    max_attempts if max_attempts is not None else "inf",
                    exc_info=True,
                )
            await asyncio.sleep(wait_seconds)
            if count_retry_after_as_attempt:
                attempt += 1
        except (TimedOut, NetworkError) as exc:
            if max_attempts is not None and attempt >= max_attempts:
                raise
            backoff_seconds: float = calculate_exponential_backoff_with_jitter(
                attempt=attempt,
                base_delay_seconds=base_delay_seconds,
                jitter_max_seconds=jitter_max_seconds,
                max_delay_seconds=max_backoff_seconds,
            )
            if on_transient_retry is not None:
                on_transient_retry(exc, attempt, backoff_seconds)
            else:
                logger.warning(
                    "run_with_transient_retry: transient_retry backoff_seconds=%.1f attempt=%d/%s error=%s",
                    backoff_seconds,
                    attempt,
                    max_attempts if max_attempts is not None else "inf",
                    type(exc).__name__,
                    exc_info=True,
                )
            await asyncio.sleep(backoff_seconds)
            attempt += 1
