"""Telegram message wrappers for sending various message types."""

import asyncio
import logging
from pathlib import Path
from typing import Final, Optional

from telegram import Bot, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import MessageLimit, ParseMode
from telegram.error import BadRequest

from .utilities import divide_message_to_chunks


# Delay between sending message chunks to avoid rate limiting
MESSAGE_SEND_DELAY_SECONDS = 0.05

# Reserved space for chunk prefix like "(99/99):\n" to avoid exceeding message limits
CHUNK_PREFIX_OVERHEAD = 20


class InvalidHtmlError(Exception):
    """Raised when message text contains invalid HTML that Telegram cannot parse.

    Users should escape their text using html.escape() before passing it to
    TelegramMessage classes if the text may contain HTML special characters.
    """

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


class TelegramMessage:
    """Base class for Telegram messages with a send method."""

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send this message via a provided bot and chat id."""
        raise NotImplementedError


class TelegramTextMessage(TelegramMessage):
    """Plain text message with automatic chunking for long messages."""

    message: str

    def __init__(self, message: str) -> None:
        """Create a text message payload."""
        self.message = message

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a chunked text message."""
        try:
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
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.message) from exc
            logger.error("TelegramTextMessage.send: failed error=%s", exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


class TelegramImageMessage(TelegramMessage):
    """Image message with optional caption."""

    image_path: str | Path
    caption: str | None

    def __init__(self, image_path: str | Path, caption: str | None = None) -> None:
        """Create an image message payload with optional caption."""
        self.image_path = image_path
        self.caption = caption

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send an image with optional caption."""
        try:
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
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.caption or "") from exc
            logger.error("TelegramImageMessage.send: failed path='%s' error=%s", image_path, exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


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

    async def send(
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
        try:
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
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.caption or "") from exc
            logger.error("TelegramDocumentMessage.send: failed path='%s' error=%s", document_path, exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


class TelegramOptionsMessage(TelegramMessage):
    """Message with inline keyboard buttons."""

    def __init__(self, text: str, reply_markup: InlineKeyboardMarkup) -> None:
        """Create a message with inline keyboard.
        
        Args:
            text: The message text.
            reply_markup: InlineKeyboardMarkup for the buttons.
        """
        self.text = text
        self.reply_markup = reply_markup
        self.sent_message: Optional[Message] = None

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Send a message with inline keyboard buttons."""
        try:
            logger.debug("TelegramOptionsMessage.send: sending")
            self.sent_message = await bot.send_message(
                chat_id=chat_id,
                text=self.text,
                reply_markup=self.reply_markup,
                parse_mode=ParseMode.HTML,
            )
            logger.info('TelegramOptionsMessage.send: sent')
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.text) from exc
            logger.error("TelegramOptionsMessage.send: failed error=%s", exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


class TelegramEditMessage(TelegramMessage):
    """Edit an existing message (update text and/or keyboard)."""

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

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Edit an existing message's text and/or keyboard."""
        try:
            logger.debug("TelegramEditMessage.send: editing message_id=%d", self.message_id)
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=self.message_id,
                text=self.text,
                reply_markup=self.reply_markup,
                parse_mode=ParseMode.HTML,
            )
            logger.info('TelegramEditMessage.send: edited message_id=%d', self.message_id)
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.text) from exc
            logger.error("TelegramEditMessage.send: failed message_id=%d error=%s", self.message_id, exc)


class TelegramCallbackAnswerMessage(TelegramMessage):
    """Answer a callback query (acknowledge button press)."""

    def __init__(self, callback_query_id: str, text: Optional[str] = None) -> None:
        """Create a callback answer payload.

        Args:
            callback_query_id: The callback query ID to answer.
            text: Optional text to show as a toast notification.
        """
        self.callback_query_id = callback_query_id
        self.text = text

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Answer a callback query to acknowledge button press."""
        try:
            await bot.answer_callback_query(
                callback_query_id=self.callback_query_id,
                text=self.text,
            )
            logger.debug('TelegramCallbackAnswerMessage.send: answered id=%s', self.callback_query_id)
        except Exception as exc:
            logger.error("TelegramCallbackAnswerMessage.send: failed id=%s error=%s", self.callback_query_id, exc)


class TelegramRemoveKeyboardMessage(TelegramMessage):
    """Remove inline keyboard from an existing message."""

    def __init__(self, message_id: int) -> None:
        """Create a remove keyboard payload.

        Args:
            message_id: The ID of the message to remove keyboard from.
        """
        self.message_id = message_id

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Remove the inline keyboard from a message."""
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=self.message_id,
                reply_markup=None,
            )
            logger.debug('TelegramRemoveKeyboardMessage.send: removed message_id=%d', self.message_id)
        except Exception as exc:
            # Ignore "message not modified" errors (keyboard already removed)
            if "message is not modified" not in str(exc).lower():
                logger.error("TelegramRemoveKeyboardMessage.send: failed message_id=%d error=%s", self.message_id, exc)


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

    async def send(
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
        try:
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
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.text) from exc
            logger.error("TelegramReplyKeyboardMessage.send: failed error=%s", exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


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

    async def send(
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
        try:
            logger.debug("TelegramRemoveReplyKeyboardMessage.send: sending")
            self.sent_message = await bot.send_message(
                chat_id=chat_id,
                text=self.text,
                reply_markup=ReplyKeyboardRemove(),
                parse_mode=ParseMode.HTML,
            )
            logger.info('TelegramRemoveReplyKeyboardMessage.send: sent')
        except Exception as exc:
            if _is_html_parse_error(exc):
                raise InvalidHtmlError(exc, self.text) from exc
            logger.error("TelegramRemoveReplyKeyboardMessage.send: failed error=%s", exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


async def _try_send_error_message(
    bot: Bot,
    chat_id: str,
    logger: logging.Logger,
    exc: Exception,
) -> None:
    """Best-effort error notification without raising further errors."""
    try:
        # Send without parse_mode to avoid any HTML parsing issues in error messages
        await bot.send_message(
            chat_id=chat_id,
            text=f"Error while sending message: {exc}",
        )
    except Exception as error_exc:
        logger.critical("_try_send_error_message: error_notification_failed error=%s", error_exc)
