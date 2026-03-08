"""Telegram message wrappers for sending various message types."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Final

from telegram import Bot, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import MessageLimit, ParseMode
from telegram.error import BadRequest, NetworkError, TimedOut

from .retry_utilities import (
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_AFTER_MAX_WAIT_SECONDS,
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    RetryAfterExceededError,
    run_with_transient_retry,
)
from .utilities import divide_message_to_chunks


# Delay between sending message chunks to avoid rate limiting
MESSAGE_SEND_DELAY_SECONDS = 0.2

# Reserved space for chunk prefix like "(99/99):\n" to avoid exceeding message limits
CHUNK_PREFIX_OVERHEAD = 20

# Maximum number of send attempts for transient send errors
SEND_MAX_ATTEMPTS: int = DEFAULT_RETRY_MAX_ATTEMPTS

# Base delay in seconds for exponential backoff with jitter (delay = base * 2^(attempt-1) + uniform jitter)
SEND_RETRY_BASE_DELAY_SECONDS: float = DEFAULT_RETRY_BASE_DELAY_SECONDS

# Maximum retry_after wait we're willing to tolerate before raising
RATE_LIMIT_MAX_WAIT_SECONDS: float = DEFAULT_RETRY_AFTER_MAX_WAIT_SECONDS


class TelegramMessage(ABC):
    """Abstract base class for Telegram messages with a send method.

    Subclasses must override ``_send_impl()`` with their happy-path send logic.
    ``BadRequest`` is treated as fatal and is re-raised (after logging with an
    HTML-escape hint). All other non-transient exceptions are logged at ERROR
    level and swallowed so the bot keeps running.
    """

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send this message, handling errors uniformly with retry logic.

        Transient errors (``NetworkError``, ``TimedOut``) are retried up to
        ``SEND_MAX_ATTEMPTS`` times with exponential backoff (attempts start
        at 1). When all retries are exhausted, they are logged at ERROR level
        and swallowed. ``RetryAfter`` errors wait the duration specified by
        Telegram plus the configured default buffer
        (``DEFAULT_RETRY_AFTER_BUFFER_SECONDS``) before retrying and do
        **not** count towards the attempt limit; if the wait exceeds
        ``RATE_LIMIT_MAX_WAIT_SECONDS``, a RuntimeError is raised.
        ``BadRequest`` is re-raised as a fatal error after logging with an
        HTML-escape hint. All other non-transient exceptions are logged at
        ERROR level and swallowed so the bot keeps running.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        class_name: str = type(self).__name__

        logger.debug("%s.send: attempting_send attempt=1/%d", class_name, SEND_MAX_ATTEMPTS)

        try:
            await run_with_transient_retry(
                lambda: self._send_impl(bot, chat_id, logger),
            )
        except RetryAfterExceededError:
            logger.error(
                "%s.send: rate_limit_exceeded max_wait=%.1fs",
                class_name,
                RATE_LIMIT_MAX_WAIT_SECONDS,
                exc_info=True,
            )
            raise RuntimeError(
                f"{class_name}.send: rate limit exceeded max wait "
                f"{RATE_LIMIT_MAX_WAIT_SECONDS:.1f}s"
            )
        except BadRequest:
            logger.error(
                "%s.send: bad_request Did you send an invalid HTML message? "
                "Try using html.escape().",
                class_name,
                exc_info=True,
            )
            raise
        except (TimedOut, NetworkError):
            logger.error(
                "%s.send: all_attempts_exhausted max_attempts=%d",
                class_name,
                SEND_MAX_ATTEMPTS,
                exc_info=True,
            )
        except Exception:
            logger.error(
                "%s.send: permanent_error_swallowed",
                class_name,
                exc_info=True,
            )
            return

    @abstractmethod
    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Subclasses override this with the actual send logic.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        ...


class TelegramTextMessage(TelegramMessage):
    """Plain text message with automatic chunking for long messages."""

    message: str

    def __init__(self, message: str) -> None:
        """Create a text message payload."""
        self.message = message

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a chunked text message.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        max_chunk_size: Final[int] = MessageLimit.MAX_TEXT_LENGTH - CHUNK_PREFIX_OVERHEAD
        chunks = divide_message_to_chunks(self.message, max_chunk_size)

        if not chunks:
            chunks = [""]

        # Add part numbers for multi-chunk messages
        if len(chunks) > 1:
            total = len(chunks)
            chunks = [
                f"({index}/{total}):\n{chunk}"
                for index, chunk in enumerate(chunks, start=1)
            ]

        logger.debug(
            "TelegramTextMessage._send_impl: sending chunks=%d",
            len(chunks),
        )
        for chunk in chunks:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
            )
            await asyncio.sleep(MESSAGE_SEND_DELAY_SECONDS)

        logger.info(
            'TelegramTextMessage._send_impl: sent chunks=%d message="%.200s"',
            len(chunks),
            self.message,
        )


class TelegramImageMessage(TelegramMessage):
    """Image message with optional caption."""

    image_path: str | Path
    caption: str | None

    def __init__(self, image_path: str | Path, caption: str | None = None) -> None:
        """Create an image message payload with optional caption."""
        self.image_path = image_path
        self.caption = caption

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send an image with optional caption.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the image to.
            logger: Logger for recording send status.
        """
        image_path = Path(self.image_path)
        logger.debug('TelegramImageMessage._send_impl: sending path="%s"', image_path)
        with image_path.open("rb") as handle:
            await bot.send_photo(
                chat_id=chat_id,
                photo=handle,
                caption=self.caption,
                parse_mode=ParseMode.HTML,
                write_timeout=60,
            )
        logger.info('TelegramImageMessage._send_impl: sent path="%s"', image_path)


class TelegramDocumentMessage(TelegramMessage):
    """Document message for sending files with optional caption."""

    file_path: str | Path
    caption: str | None

    def __init__(self, file_path: str | Path, caption: str | None = None) -> None:
        """Create a document message payload with optional caption.

        Args:
            file_path: Path to the document file to send.
            caption: Optional caption text for the document.
        """
        self.file_path = file_path
        self.caption = caption

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a document file with optional caption.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the document to.
            logger: Logger for recording send status.
        """
        document_path = Path(self.file_path)
        logger.debug('TelegramDocumentMessage._send_impl: sending path="%s"', document_path)
        with document_path.open("rb") as handle:
            await bot.send_document(
                chat_id=chat_id,
                document=handle,
                caption=self.caption,
                parse_mode=ParseMode.HTML,
                write_timeout=120,
            )
        logger.info('TelegramDocumentMessage._send_impl: sent path="%s"', document_path)


class TelegramOptionsMessage(TelegramMessage):
    """Message with inline keyboard buttons."""

    text: str
    reply_markup: InlineKeyboardMarkup
    sent_message: Message | None

    def __init__(self, text: str, reply_markup: InlineKeyboardMarkup) -> None:
        """Create a message with inline keyboard.

        Args:
            text: The message text.
            reply_markup: InlineKeyboardMarkup for the buttons.
        """
        self.text = text
        self.reply_markup = reply_markup
        self.sent_message = None

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a message with inline keyboard buttons.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        logger.debug("TelegramOptionsMessage._send_impl: sending")
        self.sent_message = await bot.send_message(
            chat_id=chat_id,
            text=self.text,
            reply_markup=self.reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info("TelegramOptionsMessage._send_impl: sent")


class TelegramEditMessage(TelegramMessage):
    """Edit an existing message (update text and/or keyboard)."""

    message_id: int
    text: str
    reply_markup: InlineKeyboardMarkup | None

    def __init__(
        self,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Create an edit message payload.

        Args:
            message_id: The ID of the message to edit.
            text: The new text content.
            reply_markup: Optional new InlineKeyboardMarkup.
        """
        self.message_id = message_id
        self.text = text
        self.reply_markup = reply_markup

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Edit an existing message's text and/or keyboard.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID of the message to edit.
            logger: Logger for recording send status.
        """
        logger.debug("TelegramEditMessage._send_impl: editing message_id=%d", self.message_id)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=self.message_id,
            text=self.text,
            reply_markup=self.reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info("TelegramEditMessage._send_impl: edited message_id=%d", self.message_id)


class TelegramCallbackAnswerMessage(TelegramMessage):
    """Answer a callback query (acknowledge button press)."""

    callback_query_id: str
    text: str | None

    def __init__(self, callback_query_id: str, text: str | None = None) -> None:
        """Create a callback answer payload.

        Args:
            callback_query_id: The callback query ID to answer.
            text: Optional text to show as a toast notification.
        """
        self.callback_query_id = callback_query_id
        self.text = text

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Answer a callback query to acknowledge button press.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID (unused for callback answers).
            logger: Logger for recording send status.
        """
        logger.debug(
            "TelegramCallbackAnswerMessage._send_impl: answering callback_query_id=%s",
            self.callback_query_id,
        )
        await bot.answer_callback_query(
            callback_query_id=self.callback_query_id,
            text=self.text,
        )
        logger.info(
            "TelegramCallbackAnswerMessage._send_impl: answered id=%s",
            self.callback_query_id,
        )


class TelegramRemoveKeyboardMessage(TelegramMessage):
    """Remove inline keyboard from an existing message."""

    message_id: int

    def __init__(self, message_id: int) -> None:
        """Create a remove keyboard payload.

        Args:
            message_id: The ID of the message to remove keyboard from.
        """
        self.message_id = message_id

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Remove the inline keyboard from a message.

        Suppresses 'message is not modified' errors since the keyboard
        may already have been removed. Re-raises all other errors for
        the base class to handle.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID of the message.
            logger: Logger for recording send status.
        """
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=self.message_id,
                reply_markup=None,
            )
            logger.debug(
                "TelegramRemoveKeyboardMessage._send_impl: removed message_id=%d",
                self.message_id,
            )
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                logger.debug(
                    "TelegramRemoveKeyboardMessage._send_impl: message_not_modified message_id=%d (expected)",
                    self.message_id,
                    exc_info=True,
                )
                return  # Expected -- keyboard was already removed
            raise  # Let the base class handle other errors


class TelegramReplyKeyboardMessage(TelegramMessage):
    """Message with a persistent reply keyboard at the bottom of the chat."""

    text: str
    keyboard: list[list[str]]
    resize_keyboard: bool
    one_time_keyboard: bool
    sent_message: Message | None

    def __init__(
        self,
        text: str,
        keyboard: list[list[str]],
        resize_keyboard: bool = True,
        one_time_keyboard: bool = False,
    ) -> None:
        """Create a message with reply keyboard.

        Args:
            text: The message text.
            keyboard: 2D list of button labels (rows x columns).
            resize_keyboard: If True, keyboard will be resized to fit buttons.
            one_time_keyboard: If True, keyboard hides after one use.
        """
        self.text = text
        self.keyboard = keyboard
        self.resize_keyboard = resize_keyboard
        self.one_time_keyboard = one_time_keyboard
        self.sent_message = None

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a message with a persistent reply keyboard.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        logger.debug("TelegramReplyKeyboardMessage._send_impl: sending")
        reply_markup = ReplyKeyboardMarkup(
            self.keyboard,
            resize_keyboard=self.resize_keyboard,
            one_time_keyboard=self.one_time_keyboard,
        )
        self.sent_message = await bot.send_message(
            chat_id=chat_id,
            text=self.text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info("TelegramReplyKeyboardMessage._send_impl: sent")


class TelegramRemoveReplyKeyboardMessage(TelegramMessage):
    """Remove the persistent reply keyboard."""

    text: str
    sent_message: Message | None

    def __init__(self, text: str = "Keyboard removed.") -> None:
        """Create a message that removes the reply keyboard.

        Args:
            text: Message text to send along with keyboard removal.
        """
        self.text = text
        self.sent_message = None

    async def _send_impl(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a message that removes the reply keyboard.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        logger.debug("TelegramRemoveReplyKeyboardMessage._send_impl: sending")
        self.sent_message = await bot.send_message(
            chat_id=chat_id,
            text=self.text,
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML,
        )
        logger.info("TelegramRemoveReplyKeyboardMessage._send_impl: sent")
