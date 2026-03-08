"""PaginatedChoiceDialog — merged inline/reply keyboard paginated choice dialog.

Redesigned with next/prev page navigation. All pages display items as
buttons — no text-input fallback.
"""

from __future__ import annotations

import math
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


class PaginatedChoiceDialog(Dialog[str], UpdatePollerMixin):
    """Leaf dialog: User selects from a paginated list of keyboard options.

    Shows ``page_size`` items per page with Next/Prev navigation buttons.
    Supports both inline keyboard (callback_query) and reply keyboard
    (text matching) via the keyboard_type parameter.

    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_CALLBACK = "__cancel__"
    NEXT_CALLBACK = "__next__"
    PREV_CALLBACK = "__prev__"
    CANCEL_LABEL = "Cancel"
    NEXT_LABEL = "Next >"
    PREV_LABEL = "< Prev"

    def __init__(
        self,
        prompt: str,
        items: list[tuple[str, str]] | Callable[[dict[str, Any]], list[tuple[str, str]]],
        page_size: int = 5,
        keyboard_type: KeyboardType = KeyboardType.INLINE,
        include_cancel: bool = True,
    ) -> None:
        """Create a paginated choice dialog.

        Args:
            prompt: The question text to display.
            items: List of (label, callback_data) tuples, or callable(context)
                returning same.
            page_size: Number of items to show per page (default 5).
            keyboard_type: Type of keyboard to use (INLINE or REPLY).
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        if callable(items):
            validate_single_arg_callable(items, "items")
        self._items = items
        self.page_size = page_size
        self.keyboard_type = keyboard_type
        self.include_cancel = include_cancel
        self._current_page: int = 0
        self._text_reminder_sent: bool = False
        self._prompt_message_id: int | None = None
        self._label_to_callback: dict[str, str] = {}

    def get_items(self) -> list[tuple[str, str]]:
        """Get items — evaluates callable if dynamic."""
        if callable(self._items):
            return self._items(self.context)
        return self._items

    @property
    def _total_pages(self) -> int:
        """Total number of pages."""
        return max(1, math.ceil(len(self.get_items()) / self.page_size))

    def _get_page_items(self, page: int) -> list[tuple[str, str]]:
        """Get items for the given page."""
        start = page * self.page_size
        end = start + self.page_size
        return self.get_items()[start:end]

    async def _run_dialog(self) -> str | DialogResult:
        """Send prompt with first page keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._current_page = 0
        self._text_reminder_sent = False

        get_logger().debug(
            "PaginatedChoiceDialog._run_dialog: sending prompt prompt='%.80s' "
            "page_size=%d keyboard_type=%s total_items=%d",
            self.prompt,
            self.page_size,
            self.keyboard_type.value,
            len(self.get_items()),
        )

        await self._send_page()
        get_logger().info("PaginatedChoiceDialog._run_dialog: prompt_sent polling")
        return await self.poll()

    async def _send_page(self) -> None:
        """Build and send the keyboard for the current page."""
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
            msg = TelegramOptionsMessage(
                self.prompt, self._build_inline_keyboard()
            )
            await get_app().send_messages(msg)
            if msg.sent_message:
                self._prompt_message_id = msg.sent_message.message_id

    def _build_label_mapping(self) -> None:
        """Build mapping from button labels to callback values for current page."""
        self._label_to_callback = {
            label: callback
            for label, callback in self._get_page_items(self._current_page)
        }

    def _build_inline_keyboard(self) -> InlineKeyboardMarkup:
        """Build inline keyboard for the current page with nav buttons."""
        buttons = [
            [InlineKeyboardButton(label, callback_data=callback)]
            for label, callback in self._get_page_items(self._current_page)
        ]
        nav_row: list[InlineKeyboardButton] = []
        if self._current_page > 0:
            nav_row.append(
                InlineKeyboardButton(self.PREV_LABEL, callback_data=self.PREV_CALLBACK)
            )
        if self._current_page < self._total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(self.NEXT_LABEL, callback_data=self.NEXT_CALLBACK)
            )
        if nav_row:
            buttons.append(nav_row)
        if self.include_cancel:
            buttons.append(
                [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
            )
        return InlineKeyboardMarkup(buttons)

    def _build_reply_keyboard(self) -> list[list[str]]:
        """Build reply keyboard for the current page with nav buttons."""
        keyboard = [
            [label]
            for label, _ in self._get_page_items(self._current_page)
        ]
        nav_row: list[str] = []
        if self._current_page > 0:
            nav_row.append(self.PREV_LABEL)
        if self._current_page < self._total_pages - 1:
            nav_row.append(self.NEXT_LABEL)
        if nav_row:
            keyboard.append(nav_row)
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])
        return keyboard

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
                "PaginatedChoiceDialog.handle_callback_update: skipped invalid_callback"
            )
            return

        if callback_data == self.CANCEL_CALLBACK:
            self.cancel()
            return

        if callback_data == self.NEXT_CALLBACK:
            if self._current_page < self._total_pages - 1:
                self._current_page += 1
                get_logger().info(
                    "PaginatedChoiceDialog.handle_callback_update: next_page page=%d",
                    self._current_page,
                )
                await self._send_page()
            return

        if callback_data == self.PREV_CALLBACK:
            if self._current_page > 0:
                self._current_page -= 1
                get_logger().info(
                    "PaginatedChoiceDialog.handle_callback_update: prev_page page=%d",
                    self._current_page,
                )
                await self._send_page()
            return

        valid_callbacks: list[str] = [
            cb for _, cb in self._get_page_items(self._current_page)
        ]
        if callback_data not in valid_callbacks:
            get_logger().debug(
                "PaginatedChoiceDialog.handle_callback_update: unknown_callback "
                "callback_data=%s",
                callback_data,
            )
            return

        self._dialog_result = callback_data
        self.state = DialogState.COMPLETE

        label: str = next(
            (lbl for lbl, cb in self.get_items() if cb == callback_data),
            callback_data,
        )
        get_logger().info(
            "PaginatedChoiceDialog.handle_callback_update: selected label=%s value=%s",
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

        if text == self.NEXT_LABEL and self._current_page < self._total_pages - 1:
            self._current_page += 1
            get_logger().info(
                "PaginatedChoiceDialog.handle_text_update: next_page page=%d",
                self._current_page,
            )
            await self._send_page()
            return

        if text == self.PREV_LABEL and self._current_page > 0:
            self._current_page -= 1
            get_logger().info(
                "PaginatedChoiceDialog.handle_text_update: prev_page page=%d",
                self._current_page,
            )
            await self._send_page()
            return

        if text in self._label_to_callback:
            callback_data: str = self._label_to_callback[text]
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage(CHECK_MARK)
            )
            self._dialog_result = callback_data
            self.state = DialogState.COMPLETE
            get_logger().info(
                "PaginatedChoiceDialog.handle_text_update: selected label=%s value=%s",
                text,
                callback_data,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {text}")
        else:
            get_logger().warning(
                "PaginatedChoiceDialog.handle_text_update: unknown_choice text=%s",
                text,
            )

    def _get_poll_result(self) -> str | DialogResult:
        """Return the dialog result after polling completes."""
        return self.dialog_result

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._current_page = 0
        self._text_reminder_sent = False
        self._prompt_message_id = None
        self._label_to_callback = {}

