"""Telegram message wrappers for sending various message types."""

import asyncio
import logging
from pathlib import Path
from typing import Final, Optional

from telegram import Bot, Message
from telegram.constants import MessageLimit, ParseMode

from .utilities import divide_message_to_chunks


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
            max_chunk_size: Final[int] = MessageLimit.MAX_TEXT_LENGTH
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
                await asyncio.sleep(0.05)

            logger.info(
                'message_sent chunks=%d message="%s"',
                len(chunks),
                self.message[:200],
            )
        except Exception as exc:
            logger.error("telegram_send_message_failed error=%s", exc)
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
            logger.debug('image_send_start path="%s"', image_path)
            with image_path.open("rb") as handle:
                caption_text = self.caption or ""
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=handle,
                    caption=caption_text if caption_text else None,
                    parse_mode=ParseMode.HTML if caption_text else None,
                )
            logger.info('image_sent path="%s"', image_path)
        except Exception as exc:
            logger.error("telegram_send_photo_failed error=%s", exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


class TelegramOptionsMessage(TelegramMessage):
    """Message with inline keyboard buttons."""

    def __init__(self, text: str, reply_markup) -> None:
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
            self.sent_message = await bot.send_message(
                chat_id=chat_id,
                text=self.text,
                reply_markup=self.reply_markup,
                parse_mode=ParseMode.HTML,
            )
            logger.info('options_message_sent')
        except Exception as exc:
            logger.error("telegram_options_message_failed error=%s", exc)
            await _try_send_error_message(bot, chat_id, logger, exc)


class TelegramEditMessage(TelegramMessage):
    """Edit an existing message (update text and/or keyboard)."""

    def __init__(
        self,
        message_id: int,
        text: str,
        reply_markup=None,
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
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=self.message_id,
                text=self.text,
                reply_markup=self.reply_markup,
                parse_mode=ParseMode.HTML,
            )
            logger.info('message_edited message_id=%d', self.message_id)
        except Exception as exc:
            logger.error("telegram_edit_message_failed error=%s", exc)


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
            logger.debug('callback_answered id=%s', self.callback_query_id)
        except Exception as exc:
            logger.error("telegram_callback_answer_failed error=%s", exc)


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
            logger.debug('keyboard_removed message_id=%d', self.message_id)
        except Exception as exc:
            # Ignore "message not modified" errors (keyboard already removed)
            if "message is not modified" not in str(exc).lower():
                logger.error("telegram_remove_keyboard_failed error=%s", exc)


async def _try_send_error_message(
    bot: Bot,
    chat_id: str,
    logger: logging.Logger,
    exc: Exception,
) -> None:
    """Best-effort error notification without raising further errors."""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Error while sending message: {exc}",
        )
    except Exception as error_exc:
        logger.error("telegram_error_message_failed error=%s", error_exc)
