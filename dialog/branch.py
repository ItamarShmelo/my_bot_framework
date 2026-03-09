"""ChoiceBranchDialog — merged inline/reply keyboard choice-branch dialog."""

from __future__ import annotations

from typing import Any

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
    CHECK_MARK,
    DIALOG_DEBUG,
    BranchesType,
    Dialog,
    DialogResult,
    DialogState,
    KeyboardType,
    _handle_callback_prelude,
    is_cancelled,
)


class ChoiceBranchDialog(Dialog[dict[str, Any] | None], UpdatePollerMixin):
    """Hybrid dialog: User selects branch via keyboard, then delegates.

    Shows a prompt with keyboard buttons, each button leads to a different
    dialog branch. Supports both inline keyboard (callback_query) and reply
    keyboard (text matching) via the keyboard_type parameter.

    Inherits UpdatePollerMixin to poll for the branch selection.
    Supports static branches dict or dynamic branches via callable.
    """

    CANCEL_CALLBACK = "__cancel__"
    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str,
        branches: BranchesType,
        include_cancel: bool = True,
        keyboard_type: KeyboardType = KeyboardType.INLINE,
    ) -> None:
        """Create a choice-branch dialog.

        Args:
            prompt: The question text to display.
            branches: Dict mapping keys to (label, dialog) tuples,
                or callable(context) returning same.
            include_cancel: If True, add a Cancel button.
            keyboard_type: Type of keyboard to use (INLINE or REPLY).
        """
        super().__init__()
        self.prompt: str = prompt
        if callable(branches):
            validate_single_arg_callable(branches, "branches")
        self._branches: BranchesType = branches
        self.include_cancel: bool = include_cancel
        self.keyboard_type: KeyboardType = keyboard_type
        self._active_branch: Dialog[Any] | None = None
        self._active_key: str | None = None
        self._choosing: bool = True
        self._label_to_key: dict[str, str] = {}

    async def _run_dialog(self) -> dict[str, Any] | None | DialogResult:
        """Show choice, poll for selection, then run selected branch."""
        self.state = DialogState.ACTIVE
        self._choosing = True
        self._active_branch = None
        self._active_key = None

        get_logger().debug(
            "ChoiceBranchDialog._run_dialog: sending prompt prompt='%.80s' keyboard_type=%s",
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

        get_logger().info("ChoiceBranchDialog._run_dialog: prompt_sent polling")

        poll_result = await self.poll()

        if is_cancelled(poll_result):
            self.state = DialogState.COMPLETE
            get_logger().info("ChoiceBranchDialog._run_dialog: cancelled")
            return DialogResult.CANCELLED

        if self._active_branch is None:
            get_logger().warning(
                "ChoiceBranchDialog._run_dialog: no_branch_selected returning_cancelled"
            )
            self._dialog_result = DialogResult.CANCELLED
            self.state = DialogState.COMPLETE
            return DialogResult.CANCELLED

        result = await self._active_branch.start(self.context)
        self._dialog_result = {self._active_key: result} if self._active_key else None
        self.state = DialogState.COMPLETE
        return self.dialog_result

    def get_branches(self) -> dict[str, tuple[str, Dialog[Any]]]:
        """Get the current branch mapping.

        Evaluates the branches callable with context if dynamic; otherwise
        returns the static dict.

        Returns:
            Dict mapping keys to (label, dialog) tuples.
        """
        if callable(self._branches):
            return self._branches(self.context)
        return self._branches

    def _build_label_mapping(self) -> None:
        """Build mapping from button labels to branch keys for text matching."""
        self._label_to_key = {
            label: key
            for key, (label, _dialog) in self.get_branches().items()
        }

    def should_stop_polling(self) -> bool:
        """Stop polling when branch selected."""
        return not self._choosing

    async def handle_callback_update(self, update: Update) -> None:
        """Handle inline keyboard callback — early return for reply mode."""
        if self.keyboard_type == KeyboardType.REPLY:
            return

        callback_data = await _handle_callback_prelude(update)
        if callback_data is None:
            get_logger().debug(
                "ChoiceBranchDialog.handle_callback_update: skipped invalid_callback"
            )
            return

        branches = self.get_branches()

        if callback_data == self.CANCEL_CALLBACK:
            self.cancel()
            self._choosing = False
            return

        if callback_data not in branches:
            get_logger().debug(
                "ChoiceBranchDialog.handle_callback_update: unknown_callback "
                "callback_data=%s",
                callback_data,
            )
            return

        self._active_key = callback_data
        label: str
        dialog: Dialog[Any]
        label, dialog = branches[callback_data]
        self._active_branch = dialog
        self._choosing = False

        get_logger().info(
            "ChoiceBranchDialog.handle_callback_update: selected key=%s label=%s",
            callback_data,
            label,
        )
        if DIALOG_DEBUG:
            await get_app().send_messages(f"Selected: {label}")

    async def handle_text_update(self, update: Update) -> None:
        """Handle reply keyboard text — early return for inline mode."""
        if self.keyboard_type == KeyboardType.INLINE:
            get_logger().debug(
                "ChoiceBranchDialog.handle_text_update: ignoring text (inline keyboard)"
            )
            return

        if not self._choosing:
            return

        if update.message is None or update.message.text is None:
            return

        text: str = update.message.text.strip()

        if text == self.CANCEL_LABEL and self.include_cancel:
            get_logger().info(
                "ChoiceBranchDialog.handle_text_update: user_cancelled"
            )
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("Cancelled.")
            )
            self.cancel()
            self._choosing = False
            return

        if text in self._label_to_key:
            branch_key: str = self._label_to_key[text]
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage(CHECK_MARK)
            )
            self._active_key = branch_key
            _, dialog = self.get_branches()[branch_key]
            self._active_branch = dialog
            self._choosing = False

            get_logger().info(
                "ChoiceBranchDialog.handle_text_update: selected key=%s label=%s",
                branch_key,
                text,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {text}")
        else:
            get_logger().warning(
                "ChoiceBranchDialog.handle_text_update: unknown_choice text=%s",
                text,
            )

    def _get_poll_result(self) -> dict[str, Any] | None | DialogResult:
        """Return the value after polling (for cancel detection)."""
        return self.dialog_result

    def _build_inline_keyboard(self) -> InlineKeyboardMarkup:
        """Build inline keyboard from branch labels and keys."""
        buttons = [
            [InlineKeyboardButton(label, callback_data=key)]
            for key, (label, _dialog) in self.get_branches().items()
        ]
        if self.include_cancel:
            buttons.append(
                [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
            )
        return InlineKeyboardMarkup(buttons)

    def _build_reply_keyboard(self) -> list[list[str]]:
        """Build reply keyboard layout from branch labels."""
        keyboard = [
            [label]
            for _key, (label, _dialog) in self.get_branches().items()
        ]
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])
        return keyboard

    def reset(self) -> None:
        """Reset choice-branch dialog."""
        super().reset()
        self._active_branch = None
        self._active_key = None
        self._choosing = True
        self._label_to_key = {}
        if not callable(self._branches):
            for _label, dialog in self._branches.values():
                dialog.reset()
