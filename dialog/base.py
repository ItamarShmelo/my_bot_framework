"""Base classes and shared infrastructure for the dialog system.

Contains Dialog, DialogState, DialogResult, KeyboardType, UpdatePollerMixin
references, and shared helpers used across all dialog submodules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

from telegram import Update

from ..accessors import get_app, get_logger
from ..polling import UpdatePollerMixin
from ..telegram_utilities import (
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
)

T = TypeVar("T")


class DialogResult(Enum):
    """Sentinel for non-value dialog outcomes (not set, cancellation, done)."""
    NOT_SET = "NOT_SET"
    CANCELLED = "CANCELLED"
    DONE = "DONE"


DONE_CALLBACK = "__done__"

BUTTON_SELECTION_REMINDER = "Please use the buttons to make a selection."

CHECK_MARK = "\u2713"


def is_cancelled(result: Any) -> bool:
    """Check if a dialog result represents cancellation."""
    return result is DialogResult.CANCELLED


DIALOG_DEBUG = False


def set_dialog_debug(enabled: bool) -> None:
    """Enable or disable dialog debug messages."""
    global DIALOG_DEBUG
    DIALOG_DEBUG = enabled


class DialogState(Enum):
    """State of a dialog conversation."""
    INACTIVE = "inactive"
    ACTIVE = "active"
    AWAITING_TEXT = "awaiting_text"
    COMPLETE = "complete"


class KeyboardType(Enum):
    """Type of keyboard to display for dialogs."""
    INLINE = "inline"
    REPLY = "reply"


class Dialog(ABC, Generic[T]):
    """Base class for all dialogs (leaf and composite).

    All dialogs share:
    - state: Current DialogState
    - dialog_result: Result after completion (T or DialogResult sentinel)
    - context: Shared dict for cross-dialog communication

    Methods:
    - start(context): Async entry point, runs dialog until complete
    - _run_dialog(): Abstract method subclasses implement
    - cancel(): Cancel and complete with CANCELLED
    - reset(): Reset for reuse
    """

    def __init__(self) -> None:
        self.state: DialogState = DialogState.INACTIVE
        self._dialog_result: T | DialogResult = DialogResult.NOT_SET
        self._context: dict[str, Any] = {}

    @abstractmethod
    async def _run_dialog(self) -> T | DialogResult:
        """Run the dialog logic. Subclasses implement this."""
        ...

    @property
    def dialog_result(self) -> T | DialogResult:
        """Result value after dialog completes."""
        return self._dialog_result

    @property
    def context(self) -> dict[str, Any]:
        """Shared context dict for cross-dialog communication."""
        return self._context

    @context.setter
    def context(self, ctx: dict[str, Any]) -> None:
        """Set the shared context."""
        self._context = ctx

    @property
    def is_complete(self) -> bool:
        """Check if dialog has completed."""
        return self.state == DialogState.COMPLETE

    @property
    def is_active(self) -> bool:
        """Check if dialog is currently active (not inactive or complete)."""
        return self.state in (DialogState.ACTIVE, DialogState.AWAITING_TEXT)

    async def start(
        self,
        context: dict[str, Any] | None = None,
    ) -> T | DialogResult:
        """Start and run the dialog until complete.

        Template method that:
        1. Calls reset() to ensure clean state
        2. Sets context from parameter (or empty dict)
        3. Calls _run_dialog() which subclasses implement

        Args:
            context: Optional shared context dict.

        Returns:
            The dialog's result value or a DialogResult sentinel.
        """
        get_logger().debug("Dialog.start: started")
        self.reset()
        self._context = context if context is not None else {}
        result = await self._run_dialog()
        get_logger().debug("Dialog.start: completed")
        return result

    def cancel(self) -> None:
        """Cancel dialog - sets dialog_result=CANCELLED, state=COMPLETE."""
        self._dialog_result = DialogResult.CANCELLED
        self.state = DialogState.COMPLETE
        get_logger().info("Dialog.cancel: cancelled")

    def reset(self) -> None:
        """Reset dialog for reuse (e.g., in LoopDialog)."""
        self.state = DialogState.INACTIVE
        self._dialog_result = DialogResult.NOT_SET
        get_logger().debug("Dialog.reset: reset state=INACTIVE")


BranchesType = (
    dict[str, tuple[str, Dialog[Any]]]
    | Callable[[dict[str, Any]], dict[str, tuple[str, Dialog[Any]]]]
)


async def _handle_callback_prelude(update: Update) -> str | None:
    """Answer callback query and remove inline keyboard.

    Shared prelude for all inline keyboard handle_callback_update methods.

    Args:
        update: Telegram Update containing the callback_query.

    Returns:
        The callback_data string, or None if the callback was invalid.
    """
    callback_query = update.callback_query
    if callback_query is None or callback_query.data is None:
        get_logger().debug(
            "_handle_callback_prelude: skipped invalid_callback has_query=%s",
            callback_query is not None,
        )
        return None
    get_logger().debug(
        "_handle_callback_prelude: answering callback_query id=%s",
        callback_query.id,
    )
    await get_app().send_messages(TelegramCallbackAnswerMessage(callback_query.id))
    if callback_query.message:
        await get_app().send_messages(
            TelegramRemoveKeyboardMessage(callback_query.message.message_id)
        )
    get_logger().debug(
        "_handle_callback_prelude: completed callback_data=%s",
        callback_query.data,
    )
    return callback_query.data
