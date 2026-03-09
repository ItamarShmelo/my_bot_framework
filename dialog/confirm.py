"""ConfirmDialog — merged inline/reply keyboard confirmation dialog."""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from ..accessors import get_app, get_logger
from ..polling import UpdatePollerMixin
from ..telegram_utilities import (
    TelegramOptionsMessage,
    TelegramReplyKeyboardMessage,
    TelegramRemoveReplyKeyboardMessage,
)
from .base import (
    BUTTON_SELECTION_REMINDER,
    CHECK_MARK,
    DIALOG_DEBUG,
    Dialog,
    DialogResult,
    DialogState,
    KeyboardType,
    _handle_callback_prelude,
)


class ConfirmDialog(Dialog[bool], UpdatePollerMixin):
    """Leaf dialog: Yes/No confirmation prompt.

    Supports both inline keyboard (callback_query) and reply keyboard (text
    matching) via the keyboard_type parameter.

    Convenience dialog for common Yes/No flows.
    Inherits UpdatePollerMixin for self-polling.
    """

    YES_CALLBACK = "__yes__"
    NO_CALLBACK = "__no__"
    CANCEL_CALLBACK = "__cancel__"
    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str,
        yes_label: str = "Yes",
        no_label: str = "No",
        include_cancel: bool = False,
        keyboard_type: KeyboardType = KeyboardType.INLINE,
    ) -> None:
        """Create a confirmation dialog.

        Args:
            prompt: The question text to display.
            yes_label: Label for the Yes button.
            no_label: Label for the No button.
            include_cancel: If True, add a Cancel button.
            keyboard_type: Type of keyboard to use (INLINE or REPLY).
        """
        super().__init__()
        self.prompt = prompt
        self.yes_label = yes_label
        self.no_label = no_label
        self.include_cancel = include_cancel
        self.keyboard_type = keyboard_type
        self._text_reminder_sent: bool = False

    async def _run_dialog(self) -> bool | DialogResult:
        """Show prompt with Yes/No buttons, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._text_reminder_sent = False

        get_logger().debug(
            "ConfirmDialog._run_dialog: sending prompt prompt='%.80s' keyboard_type=%s",
            self.prompt,
            self.keyboard_type.value,
        )

        if self.keyboard_type == KeyboardType.REPLY:
            keyboard: list[list[str]] = [[self.yes_label, self.no_label]]
            if self.include_cancel:
                keyboard.append([self.CANCEL_LABEL])
            await get_app().send_messages(
                TelegramReplyKeyboardMessage(
                    text=self.prompt,
                    keyboard=keyboard,
                    one_time_keyboard=True,
                )
            )
        else:
            buttons = [
                [
                    InlineKeyboardButton(self.yes_label, callback_data=self.YES_CALLBACK),
                    InlineKeyboardButton(self.no_label, callback_data=self.NO_CALLBACK),
                ]
            ]
            if self.include_cancel:
                buttons.append(
                    [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
                )
            await get_app().send_messages(
                TelegramOptionsMessage(self.prompt, InlineKeyboardMarkup(buttons))
            )

        get_logger().info("ConfirmDialog._run_dialog: prompt_sent polling")
        return await self.poll()

    def should_stop_polling(self) -> bool:
        """Stop polling when dialog is complete."""
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Handle inline keyboard callback — early return for reply mode."""
        if self.keyboard_type == KeyboardType.REPLY:
            return

        callback_data = await _handle_callback_prelude(update)
        if callback_data is None:
            get_logger().debug(
                "ConfirmDialog.handle_callback_update: skipped invalid_callback"
            )
            return

        if callback_data == self.CANCEL_CALLBACK:
            self.cancel()
        elif callback_data == self.YES_CALLBACK:
            self._dialog_result = True
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ConfirmDialog.handle_callback_update: selected value=True label=%s",
                self.yes_label,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"{self.yes_label}")
        elif callback_data == self.NO_CALLBACK:
            self._dialog_result = False
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ConfirmDialog.handle_callback_update: selected value=False label=%s",
                self.no_label,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"{self.no_label}")
        else:
            get_logger().debug(
                "ConfirmDialog.handle_callback_update: unknown_callback callback_data=%s",
                callback_data,
            )

    async def handle_text_update(self, update: Update) -> None:
        """Handle reply keyboard text — early return with reminder for inline mode."""
        if self.keyboard_type == KeyboardType.INLINE:
            if self.is_active and not self._text_reminder_sent:
                self._text_reminder_sent = True
                await get_app().send_messages(BUTTON_SELECTION_REMINDER)
            return

        if update.message is None or update.message.text is None:
            return

        text: str = update.message.text.strip()

        if text == self.CANCEL_LABEL and self.include_cancel:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("Cancelled.")
            )
            self.cancel()
            return

        if text == self.yes_label:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage(CHECK_MARK)
            )
            self._dialog_result = True
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ConfirmDialog.handle_text_update: selected value=True label=%s",
                self.yes_label,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"{self.yes_label}")
            return

        if text == self.no_label:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage(CHECK_MARK)
            )
            self._dialog_result = False
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ConfirmDialog.handle_text_update: selected value=False label=%s",
                self.no_label,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"{self.no_label}")
            return

        get_logger().warning(
            "ConfirmDialog.handle_text_update: unknown_choice text=%s",
            text,
        )

    def _get_poll_result(self) -> bool | DialogResult:
        """Return the dialog result after polling completes."""
        return self.dialog_result

