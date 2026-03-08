"""UserInputDialog — text input dialog with optional validation."""

from __future__ import annotations

from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from ..accessors import get_app, get_logger
from ..polling import UpdatePollerMixin
from ..telegram_utilities import (
    TelegramOptionsMessage,
    TelegramReplyKeyboardMessage,
    TelegramRemoveKeyboardMessage,
    TelegramRemoveReplyKeyboardMessage,
)
from .base import (
    DIALOG_DEBUG,
    Dialog,
    DialogResult,
    DialogState,
    KeyboardType,
    _handle_callback_prelude,
)


class UserInputDialog(Dialog[str], UpdatePollerMixin):
    """Leaf dialog: User enters text.

    Optionally validates input before accepting.
    Inherits UpdatePollerMixin for self-polling.

    The keyboard_type parameter controls whether the Cancel button is shown
    as an inline keyboard button (INLINE) or a reply keyboard button (REPLY).
    """

    CANCEL_CALLBACK = "__cancel__"
    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str | Callable[[], str],
        validator: Callable[[str], tuple[bool, str]] | None = None,
        include_cancel: bool = True,
        keyboard_type: KeyboardType = KeyboardType.INLINE,
    ) -> None:
        """Create a text input dialog.

        Args:
            prompt: The question text to display or a callable that returns it.
            validator: Optional callable(text) -> (is_valid, error_message).
            include_cancel: If True, add a Cancel button.
            keyboard_type: Type of keyboard to use for Cancel button
                (INLINE or REPLY). Defaults to INLINE.
        """
        super().__init__()
        self._prompt: Callable[[], str]
        self.prompt = prompt
        self.validator = validator
        self.include_cancel = include_cancel
        self.keyboard_type = keyboard_type
        self._prompt_message_id: int | None = None

    @property
    def prompt(self) -> str:
        """Resolved prompt text for this dialog."""
        return self._prompt()

    @prompt.setter
    def prompt(self, value: str | Callable[[], str]) -> None:
        """Set prompt as a string or callable returning a string."""
        if callable(value):
            self._prompt = value
        else:
            self._prompt = lambda: value

    async def _run_dialog(self) -> str | DialogResult:
        """Show prompt and poll until text input received."""
        self.state = DialogState.AWAITING_TEXT
        get_logger().debug(
            "UserInputDialog._run_dialog: started keyboard_type=%s include_cancel=%s",
            self.keyboard_type.value,
            self.include_cancel,
        )

        if self.keyboard_type == KeyboardType.REPLY:
            if self.include_cancel:
                await get_app().send_messages(
                    TelegramReplyKeyboardMessage(
                        text=self.prompt,
                        keyboard=[[self.CANCEL_LABEL]],
                        one_time_keyboard=False,
                    )
                )
            else:
                await get_app().send_messages(self.prompt)
        elif self.keyboard_type == KeyboardType.INLINE:
            if self.include_cancel:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(self.CANCEL_LABEL, callback_data=self.CANCEL_CALLBACK)]
                ])
                msg = TelegramOptionsMessage(self.prompt, keyboard)
                await get_app().send_messages(msg)
                if msg.sent_message:
                    self._prompt_message_id = msg.sent_message.message_id
            else:
                await get_app().send_messages(self.prompt)

        return await self.poll()

    def should_stop_polling(self) -> bool:
        """Stop polling when dialog is complete."""
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Handle inline keyboard cancel button."""
        callback_data = await _handle_callback_prelude(update)
        if callback_data is None:
            get_logger().debug(
                "UserInputDialog.handle_callback_update: skipped invalid_callback"
            )
            return

        if callback_data == self.CANCEL_CALLBACK:
            self.cancel()

    async def handle_text_update(self, update: Update) -> None:
        """Validate and accept text input, remove keyboard from previous prompt."""
        if update.message is None or update.message.text is None:
            get_logger().debug(
                "UserInputDialog.handle_text_update: skipped_no_text update_id=%s "
                "has_message=%s",
                update.update_id,
                update.message is not None,
            )
            return
        if self.state != DialogState.AWAITING_TEXT:
            get_logger().debug(
                "UserInputDialog.handle_text_update: wrong_state state=%s",
                self.state.value,
            )
            return

        text: str = update.message.text.strip()

        if self.keyboard_type == KeyboardType.REPLY and text == self.CANCEL_LABEL and self.include_cancel:
            await get_app().send_messages(TelegramRemoveReplyKeyboardMessage("Cancelled."))
            self.cancel()
            return

        if self.validator:
            is_valid: bool
            error_msg: str
            is_valid, error_msg = self.validator(text)
            if not is_valid:
                get_logger().info(
                    "UserInputDialog.handle_text_update: validation_failed error=%s keyboard_type=%s text_preview=%.50s",
                    error_msg,
                    self.keyboard_type.value,
                    text,
                )
                if self.keyboard_type == KeyboardType.REPLY:
                    keyboard: list[list[str]] = [[self.CANCEL_LABEL]] if self.include_cancel else []
                    await get_app().send_messages(
                        TelegramReplyKeyboardMessage(
                            text=f"{error_msg}\n\n{self.prompt}",
                            keyboard=keyboard,
                            one_time_keyboard=False,
                        )
                    )
                    return
                elif self.keyboard_type == KeyboardType.INLINE:
                    if self.include_cancel:
                        inline_keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton(self.CANCEL_LABEL, callback_data=self.CANCEL_CALLBACK)]
                        ])
                        msg = TelegramOptionsMessage(f"{error_msg}\n\n{self.prompt}", inline_keyboard)
                        await get_app().send_messages(msg)
                        if msg.sent_message:
                            self._prompt_message_id = msg.sent_message.message_id
                    else:
                        await get_app().send_messages(f"{error_msg}\n\n{self.prompt}")
                    return

        self._dialog_result = text
        self.state = DialogState.COMPLETE

        text_preview: str = text[:50] if len(text) > 50 else text
        get_logger().info("UserInputDialog.handle_text_update: received text=%s", text_preview)

        if self.keyboard_type == KeyboardType.INLINE and self._prompt_message_id is not None:
            await get_app().send_messages(TelegramRemoveKeyboardMessage(self._prompt_message_id))
            self._prompt_message_id = None

        if DIALOG_DEBUG:
            await get_app().send_messages(f"Received: {text}")

    def _get_poll_result(self) -> str | DialogResult:
        """Return the dialog result after polling completes."""
        return self.dialog_result

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._prompt_message_id = None
