"""Telegram message wrappers for sending various message types."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Final, Optional

from telegram import Bot, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import MessageLimit, ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from .utilities import divide_message_to_chunks


# Delay between sending message chunks to avoid rate limiting
MESSAGE_SEND_DELAY_SECONDS = 0.05

# Reserved space for chunk prefix like "(99/99):\n" to avoid exceeding message limits
CHUNK_PREFIX_OVERHEAD = 20

# Maximum number of retry attempts for transient send errors
SEND_MAX_RETRIES: int = 3

# Base delay in seconds for exponential backoff between retries (delay = base * 2^attempt)
SEND_RETRY_BASE_DELAY_SECONDS: float = 1.0


class InvalidHtmlError(Exception):
    """Raised when message text contains invalid HTML that Telegram cannot parse.

    This is a fatal error -- it propagates up and terminates the bot so the
    developer notices and fixes it. Users should escape their text using
    html.escape() before passing it to TelegramMessage classes if the text
    may contain HTML special characters.
    """

    original_error: Exception
    text: str

    def __init__(self, original_error: Exception, text: str) -> None:
        """Create an InvalidHtmlError with context about the failure.

        Args:
            original_error: The original Telegram API error.
            text: The text that caused the parsing error (truncated for display).
        """
        truncated_text = text[:100] + "..." if len(text) > 100 else text
        super().__init__(
            f"Message contains invalid HTML that Telegram cannot parse. "
            f"Use html.escape() on your text before passing it to TelegramMessage. "
            f"Original error: {original_error}. "
            f"Text (truncated): {truncated_text!r}"
        )
        self.original_error = original_error
        self.text = text


def _is_html_parse_error(exc: Exception) -> bool:
    """Check if an exception is an HTML parsing error from Telegram."""
    if not isinstance(exc, BadRequest):
        return False
    error_msg = str(exc).lower()
    return "can't parse entities" in error_msg or "parse entities" in error_msg


class TelegramMessage(ABC):
    """Abstract base class for Telegram messages with a send method.

    Subclasses must override ``_send_impl()`` with their happy-path send logic.
    ``InvalidHtmlError`` is re-raised as a fatal error -- it propagates up and
    terminates the bot. All other exceptions are logged at ERROR level and
    swallowed so the bot keeps running.

    Subclasses that send HTML-parsed text should override ``_get_error_text()``
    to return the text that could trigger ``InvalidHtmlError``.
    """

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send this message, handling errors uniformly with retry logic.

        Transient errors (``NetworkError``, ``TimedOut``) are retried up to
        ``SEND_MAX_RETRIES`` times with exponential backoff.  ``RetryAfter``
        errors wait the duration specified by Telegram before retrying.
        ``InvalidHtmlError`` is re-raised as a fatal error.  All other
        exceptions are logged at ERROR level and swallowed so the bot
        keeps running.

        Args:
            bot: The Telegram Bot instance.
            chat_id: The chat ID to send the message to.
            logger: Logger for recording send status.
        """
        class_name: str = type(self).__name__

        for attempt in range(SEND_MAX_RETRIES):
            logger.debug(
                "%s.send: attempting_send attempt=%d/%d",
                class_name,
                attempt + 1,
                SEND_MAX_RETRIES,
            )
            try:
                await self._send_impl(bot, chat_id, logger)
                if attempt > 0:
                    logger.info(
                        "%s.send: succeeded_after_retry attempt=%d/%d",
                        class_name,
                        attempt + 1,
                        SEND_MAX_RETRIES,
                    )
                return  # Success -- exit immediately
            except InvalidHtmlError:
                raise  # Fatal -- propagates up and terminates the bot
            except RetryAfter as exc:
                retry_after = exc.retry_after
                wait_seconds: int = (
                    int(retry_after.total_seconds())
                    if isinstance(retry_after, timedelta)
                    else retry_after
                )
                logger.warning(
                    "%s.send: rate_limited retry_after=%ds attempt=%d/%d",
                    class_name,
                    wait_seconds,
                    attempt + 1,
                    SEND_MAX_RETRIES,
                )
                await asyncio.sleep(wait_seconds)
            except (TimedOut, NetworkError) as exc:
                # Exponential backoff: delay = base * 2^attempt (1s, 2s, 4s for attempts 0, 1, 2)
                backoff_seconds: float = SEND_RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                logger.warning(
                    "%s.send: transient_error error=%s backoff=%.1fs attempt=%d/%d",
                    class_name,
                    type(exc).__name__,
                    backoff_seconds,
                    attempt + 1,
                    SEND_MAX_RETRIES,
                )
                await asyncio.sleep(backoff_seconds)
            except Exception as exc:
                if _is_html_parse_error(exc):
                    raise InvalidHtmlError(exc, self._get_error_text()) from exc
                logger.error(
                    "%s.send: permanent_error error=%s attempt=%d/%d",
                    class_name,
                    type(exc).__name__,
                    attempt + 1,
                    SEND_MAX_RETRIES,
                    exc_info=True,
                )
                return  # Non-retryable -- swallow and continue

        logger.error(
            "%s.send: all_retries_exhausted max_retries=%d",
            class_name,
            SEND_MAX_RETRIES,
        )

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

    def _get_error_text(self) -> str:
        """Return the text to include in InvalidHtmlError context.

        Override in subclasses that send HTML-parsed text.
        """
        return ""


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

        for chunk in chunks:
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
            )
            await asyncio.sleep(MESSAGE_SEND_DELAY_SECONDS)

        logger.info(
            'TelegramTextMessage.send: sent chunks=%d message="%.200s"',
            len(chunks),
            self.message,
        )

    def _get_error_text(self) -> str:
        """Return the message text for InvalidHtmlError context."""
        return self.message


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
        logger.debug('TelegramImageMessage.send: sending path="%s"', image_path)
        with image_path.open("rb") as handle:
            caption_text = self.caption or ""
            await bot.send_photo(
                chat_id=chat_id,
                photo=handle,
                caption=caption_text if caption_text else None,
                parse_mode=ParseMode.HTML if caption_text else None,
            )
        logger.info('TelegramImageMessage.send: sent path="%s"', image_path)

    def _get_error_text(self) -> str:
        """Return the caption text for InvalidHtmlError context."""
        return self.caption or ""


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
        logger.debug('TelegramDocumentMessage.send: sending path="%s"', document_path)
        with document_path.open("rb") as handle:
            caption_text = self.caption or ""
            await bot.send_document(
                chat_id=chat_id,
                document=handle,
                caption=caption_text if caption_text else None,
                parse_mode=ParseMode.HTML if caption_text else None,
            )
        logger.info('TelegramDocumentMessage.send: sent path="%s"', document_path)

    def _get_error_text(self) -> str:
        """Return the caption text for InvalidHtmlError context."""
        return self.caption or ""


class TelegramOptionsMessage(TelegramMessage):
    """Message with inline keyboard buttons."""

    text: str
    reply_markup: InlineKeyboardMarkup
    sent_message: Optional[Message]

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
        logger.debug("TelegramOptionsMessage.send: sending")
        self.sent_message = await bot.send_message(
            chat_id=chat_id,
            text=self.text,
            reply_markup=self.reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info('TelegramOptionsMessage.send: sent')

    def _get_error_text(self) -> str:
        """Return the message text for InvalidHtmlError context."""
        return self.text


class TelegramEditMessage(TelegramMessage):
    """Edit an existing message (update text and/or keyboard)."""

    message_id: int
    text: str
    reply_markup: Optional[InlineKeyboardMarkup]

    def __init__(
        self,
        message_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
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
        logger.debug("TelegramEditMessage.send: editing message_id=%d", self.message_id)
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=self.message_id,
            text=self.text,
            reply_markup=self.reply_markup,
            parse_mode=ParseMode.HTML,
        )
        logger.info('TelegramEditMessage.send: edited message_id=%d', self.message_id)

    def _get_error_text(self) -> str:
        """Return the message text for InvalidHtmlError context."""
        return self.text


class TelegramCallbackAnswerMessage(TelegramMessage):
    """Answer a callback query (acknowledge button press)."""

    callback_query_id: str
    text: Optional[str]

    def __init__(self, callback_query_id: str, text: Optional[str] = None) -> None:
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
        await bot.answer_callback_query(
            callback_query_id=self.callback_query_id,
            text=self.text,
        )
        logger.debug('TelegramCallbackAnswerMessage.send: answered id=%s', self.callback_query_id)


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
            logger.debug('TelegramRemoveKeyboardMessage.send: removed message_id=%d', self.message_id)
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return  # Expected -- keyboard was already removed
            raise  # Let the base class handle other errors


class TelegramReplyKeyboardMessage(TelegramMessage):
    """Message with a persistent reply keyboard at the bottom of the chat."""

    text: str
    keyboard: list[list[str]]
    resize_keyboard: bool
    one_time_keyboard: bool
    sent_message: Optional[Message]

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
        logger.debug("TelegramReplyKeyboardMessage.send: sending")
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
        logger.info('TelegramReplyKeyboardMessage.send: sent')

    def _get_error_text(self) -> str:
        """Return the message text for InvalidHtmlError context."""
        return self.text


class TelegramRemoveReplyKeyboardMessage(TelegramMessage):
    """Remove the persistent reply keyboard."""

    text: str
    sent_message: Optional[Message]

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
        logger.debug("TelegramRemoveReplyKeyboardMessage.send: sending")
        self.sent_message = await bot.send_message(
            chat_id=chat_id,
            text=self.text,
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=ParseMode.HTML,
        )
        logger.info('TelegramRemoveReplyKeyboardMessage.send: sent')

    def _get_error_text(self) -> str:
        """Return the message text for InvalidHtmlError context."""
        return self.text
