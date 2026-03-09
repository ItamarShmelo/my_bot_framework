"""ChoiceDialog — merged inline/reply keyboard choice dialog."""

from __future__ import annotations

from typing import Any, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from ..accessors import get_app, get_logger
from ..polling import UpdatePollerMixin
from ..utilities import validate_single_arg_callable
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


class ChoiceDialog(Dialog[str], UpdatePollerMixin):
    """Leaf dialog: User selects from keyboard options.

    Supports both inline keyboard (callback_query) and reply keyboard (text
    matching) via the keyboard_type parameter.

    Supports static choices list or dynamic choices via callable.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_CALLBACK = "__cancel__"
    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str,
        choices: list[tuple[str, str]] | Callable[[dict[str, Any]], list[tuple[str, str]]],
        include_cancel: bool = True,
        keyboard_type: KeyboardType = KeyboardType.INLINE,
    ) -> None:
        """Create a choice dialog.

        Args:
            prompt: The question text to display.
            choices: List of (label, callback_data) tuples, or callable(context)
                returning same.
            include_cancel: If True, add a Cancel button.
            keyboard_type: Type of keyboard to use (INLINE or REPLY).
        """
        super().__init__()
        self.prompt = prompt
        if callable(choices):
            validate_single_arg_callable(choices, "choices")
        self._choices = choices
        self.include_cancel = include_cancel
        self.keyboard_type = keyboard_type
        self._text_reminder_sent: bool = False
        self._label_to_callback: dict[str, str] = {}

    async def _run_dialog(self) -> str | DialogResult:
        """Send prompt with keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._text_reminder_sent = False

        get_logger().debug(
            "ChoiceDialog._run_dialog: sending prompt prompt='%.80s' keyboard_type=%s",
            self.prompt,
            self.keyboard_type.value,
        )

        if self.keyboard_type == KeyboardType.REPLY:
            self._build_label_mapping()
            await get_app().send_messages(
                TelegramReplyKeyboardMessage(
                    text=self.prompt,
                    keyboard=self._build_reply_keyboard(),
                    one_time_keyboard=True,
                )
            )
        else:
            await get_app().send_messages(
                TelegramOptionsMessage(self.prompt, self._build_inline_keyboard())
            )

        get_logger().info("ChoiceDialog._run_dialog: prompt_sent polling")
        return await self.poll()

    def get_choices(self) -> list[tuple[str, str]]:
        """Get choices — evaluates callable if dynamic."""
        if callable(self._choices):
            return self._choices(self.context)
        return self._choices

    def _build_label_mapping(self) -> None:
        """Build mapping from button labels to callback_data values."""
        self._label_to_callback = {
            label: callback for label, callback in self.get_choices()
        }

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
                "ChoiceDialog.handle_callback_update: skipped invalid_callback"
            )
            return

        if callback_data == self.CANCEL_CALLBACK:
            self.cancel()
            return

        valid_callbacks: list[str] = [cb for _, cb in self.get_choices()]
        if callback_data not in valid_callbacks:
            get_logger().debug(
                "ChoiceDialog.handle_callback_update: unknown_callback callback_data=%s",
                callback_data,
            )
            return

        self._dialog_result = callback_data
        self.state = DialogState.COMPLETE

        label: str = next(
            (lbl for lbl, cb in self.get_choices() if cb == callback_data),
            callback_data,
        )
        get_logger().info(
            "ChoiceDialog.handle_callback_update: selected label=%s value=%s",
            label,
            callback_data,
        )
        if DIALOG_DEBUG:
            await get_app().send_messages(f"Selected: {label}")

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

        if text in self._label_to_callback:
            callback_data: str = self._label_to_callback[text]
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage(CHECK_MARK)
            )
            self._dialog_result = callback_data
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ChoiceDialog.handle_text_update: selected label=%s value=%s",
                text,
                callback_data,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {text}")
        else:
            get_logger().warning(
                "ChoiceDialog.handle_text_update: unknown_choice text=%s",
                text,
            )

    def _get_poll_result(self) -> str | DialogResult:
        """Return the dialog result after polling completes."""
        return self.dialog_result

    def _build_inline_keyboard(self) -> InlineKeyboardMarkup:
        """Build inline keyboard from choices."""
        buttons = [
            [InlineKeyboardButton(label, callback_data=callback)]
            for label, callback in self.get_choices()
        ]
        if self.include_cancel:
            buttons.append(
                [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
            )
        return InlineKeyboardMarkup(buttons)

    def _build_reply_keyboard(self) -> list[list[str]]:
        """Build reply keyboard layout from choices."""
        keyboard = [[label] for label, _ in self.get_choices()]
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])
        return keyboard

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._text_reminder_sent = False
        self._label_to_callback = {}

