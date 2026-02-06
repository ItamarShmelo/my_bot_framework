"""Dialog system for interactive multi-step Telegram conversations.

This module implements the Composite pattern for building complex dialogs
from simple atomic components (leaf dialogs) and composites.

Leaf dialogs (one question each):
- ChoiceDialog: User selects from keyboard options
- PaginatedChoiceDialog: User selects from paginated keyboard options
- UserInputDialog: User enters text
- ConfirmDialog: Yes/No prompt
- EditEventDialog: Edit an event's editable attributes via inline keyboard

Composite dialogs:
- SequenceDialog: Run dialogs in order
- BranchDialog: Condition-based branching
- ChoiceBranchDialog: User selects branch via keyboard
- LoopDialog: Repeat until exit condition
"""

import asyncio
import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from .accessors import get_app, get_logger
from .polling import UpdatePollerMixin
from .telegram_utilities import (
    TelegramMessage,
    TelegramTextMessage,
    TelegramOptionsMessage,
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
    TelegramReplyKeyboardMessage,
    TelegramRemoveReplyKeyboardMessage,
)

if TYPE_CHECKING:
    from .event import ActivateOnConditionEvent
    from .editable import EditableAttribute


# Sentinel for cancelled dialogs - distinct from None which could be a valid value
CANCELLED = object()


def is_cancelled(result: Any) -> bool:
    """Check if a dialog result represents cancellation."""
    return result is CANCELLED


# Global debug flag - when True, dialogs send confirmation messages to user
# When False, only logs are produced (cleaner UX)
DIALOG_DEBUG = False


def set_dialog_debug(enabled: bool) -> None:
    """Enable or disable dialog debug messages."""
    global DIALOG_DEBUG
    DIALOG_DEBUG = enabled


# Type alias for dialog results - nested dictionary mirroring dialog structure
DialogResult = Union[Any, Dict[str, "DialogResult"]]


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


@dataclass
class DialogResponse:
    """Response from a dialog - text with optional inline keyboard.

    Attributes:
        text: The message text to send/edit.
        keyboard: Optional InlineKeyboardMarkup for buttons.
        edit_message: If True, edit the existing message. If False, send new.
    """
    text: str
    keyboard: Optional[InlineKeyboardMarkup] = None
    edit_message: bool = True

    # Sentinel for "no message change needed" - dialog consumed input but no UI update
    NO_CHANGE: "DialogResponse" = None  # type: ignore[assignment]


# Initialize the NO_CHANGE sentinel after class definition
DialogResponse.NO_CHANGE = DialogResponse(text="", keyboard=None, edit_message=False)


class Dialog(ABC):
    """Base class for all dialogs (leaf and composite).

    All dialogs share:
    - state: Current DialogState
    - value: Result after completion
    - context: Shared dict for cross-dialog communication

    Methods:
    - start(context): Async entry point, runs dialog until complete
    - _run_dialog(): Abstract method subclasses implement
    - build_result(): Build standardized DialogResult
    - handle_callback(data): Handle button press (used internally)
    - handle_text_input(text): Handle text input (used internally)
    - cancel(): Cancel and complete with CANCELLED
    - reset(): Reset for reuse
    """

    def __init__(self) -> None:
        self.state = DialogState.INACTIVE
        self._value: Any = None
        self._context: Dict[str, Any] = {}

    @property
    def value(self) -> Any:
        """Result value after dialog completes."""
        return self._value

    @property
    def context(self) -> Dict[str, Any]:
        """Shared context dict for cross-dialog communication."""
        return self._context

    @context.setter
    def context(self, ctx: Dict[str, Any]) -> None:
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
        context: Optional[Dict[str, Any]] = None,
    ) -> DialogResult:
        """Start and run the dialog until complete.

        Template method that:
        1. Calls reset() to ensure clean state
        2. Sets context from parameter (or empty dict)
        3. Calls _run_dialog() which subclasses implement

        Args:
            context: Optional shared context dict.

        Returns:
            DialogResult
        """
        self.reset()
        self._context = context if context is not None else {}
        return await self._run_dialog()

    @abstractmethod
    async def _run_dialog(self) -> DialogResult:
        """Run the dialog logic. Subclasses implement this."""
        ...

    @abstractmethod
    def build_result(self) -> DialogResult:
        """Build the standardized result for this dialog.

        Each dialog type implements its own result structure.
        """
        ...

    @abstractmethod
    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle inline keyboard button press."""
        ...

    @abstractmethod
    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Handle text input from user."""
        ...

    def cancel(self) -> DialogResponse:
        """Cancel dialog - sets value=CANCELLED, state=COMPLETE."""
        self._value = CANCELLED
        self.state = DialogState.COMPLETE
        logger = get_logger()
        logger.info("Dialog.cancel: cancelled")
        return DialogResponse(text="Cancelled.", keyboard=None, edit_message=False)

    def reset(self) -> None:
        """Reset dialog for reuse (e.g., in LoopDialog)."""
        self.state = DialogState.INACTIVE
        self._value = None


# =============================================================================
# LEAF DIALOGS
# =============================================================================

class InlineKeyboardChoiceDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User selects from inline keyboard options.

    Supports static choices list or dynamic choices via callable.
    Inherits UpdatePollerMixin for self-polling.
    Uses inline keyboard buttons that send callback_query events.
    """

    CANCEL_CALLBACK = "__cancel__"

    def __init__(
        self,
        prompt: str,
        choices: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]],
        include_cancel: bool = True,
    ) -> None:
        """Create a choice dialog.

        Args:
            prompt: The question text to display.
            choices: List of (label, callback_data) tuples, or callable(context) returning same.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        if callable(choices):
            sig = inspect.signature(choices)
            params = [p for p in sig.parameters.values()
                      if p.default is inspect.Parameter.empty]
            assert len(params) == 1, (
                f"choices callable must accept exactly 1 argument (context), "
                f"got {len(params)} required parameters"
            )
        self._choices = choices
        self.include_cancel = include_cancel
        self._text_reminder_sent = False  # Spam control

    def get_choices(self) -> List[Tuple[str, str]]:
        """Get choices - evaluates callable if dynamic."""
        if callable(self._choices):
            return self._choices(self.context)
        return self._choices

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        callback_query = update.callback_query
        if callback_query is None or callback_query.data is None:
            return
        # Answer callback and remove keyboard
        await get_app().send_messages(TelegramCallbackAnswerMessage(callback_query.id))

        if callback_query.message:
            await get_app().send_messages(
                TelegramRemoveKeyboardMessage(callback_query.message.message_id)
            )

        # Delegate to dialog's handle_callback
        response = self.handle_callback(callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """ChoiceDialog ignores text - clarify to user (once per activation)."""
        if self.is_active and not self._text_reminder_sent:
            self._text_reminder_sent = True
            await get_app().send_messages("Please use the buttons to make a selection.")

    def _get_poll_result(self) -> Any:
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return

        if response.keyboard:
            await get_app().send_messages(TelegramOptionsMessage(response.text, response.keyboard))
        else:
            await get_app().send_messages(response.text)

    async def _run_dialog(self) -> DialogResult:
        """Send prompt with keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._text_reminder_sent = False  # Reset spam control

        # Send initial message with keyboard
        response = DialogResponse(
            text=self.prompt,
            keyboard=self._build_keyboard(),
            edit_message=False,
        )
        await self._send_response(response)

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle button press - set value and complete."""
        if callback_data == self.CANCEL_CALLBACK:
            return self.cancel()

        # Verify callback is valid
        valid_callbacks = [cb for _, cb in self.get_choices()]
        if callback_data not in valid_callbacks:
            return None  # Unknown callback

        self._value = callback_data
        self.state = DialogState.COMPLETE

        # Find the label for the selected choice
        label = next((lbl for lbl, cb in self.get_choices() if cb == callback_data), callback_data)

        # Log selection
        get_logger().info("InlineKeyboardChoiceDialog.handle_callback: selected label=%s value=%s", label, callback_data)

        # Only send confirmation message if debug mode is enabled
        if DIALOG_DEBUG:
            return DialogResponse(
                text=f"Selected: {label}",
                keyboard=None,
                edit_message=False,
            )
        return DialogResponse.NO_CHANGE

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Choice dialogs don't accept text - return None."""
        return None

    def _build_keyboard(self) -> InlineKeyboardMarkup:
        """Build keyboard from choices."""
        buttons = [
            [InlineKeyboardButton(label, callback_data=callback)]
            for label, callback in self.get_choices()
        ]
        if self.include_cancel:
            buttons.append([InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)])
        return InlineKeyboardMarkup(buttons)


class InlineKeyboardPaginatedChoiceDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User selects from a paginated list of inline keyboard options.

    Shows first `page_size` items as buttons. If there are more items,
    shows a "More..." button. Clicking "More..." displays all remaining
    items as a numbered text list and prompts for text input.

    Uses inline keyboard buttons that send callback_query events.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_CALLBACK = "__cancel__"
    MORE_CALLBACK = "__more__"

    def __init__(
        self,
        prompt: str,
        items: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]],
        page_size: int = 5,
        more_label: str = "More...",
        include_cancel: bool = True,
    ) -> None:
        """Create a paginated choice dialog.

        Args:
            prompt: The question text to display.
            items: List of (label, callback_data) tuples, or callable(context) returning same.
            page_size: Number of items to show as buttons (default 5).
            more_label: Label for the "show more" button.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        if callable(items):
            sig = inspect.signature(items)
            params = [p for p in sig.parameters.values()
                      if p.default is inspect.Parameter.empty]
            assert len(params) == 1, (
                f"items callable must accept exactly 1 argument (context), "
                f"got {len(params)} required parameters"
            )
        self._items = items
        self.page_size = page_size
        self.more_label = more_label
        self.include_cancel = include_cancel
        self._showing_more = False  # True when in text input mode for remaining items
        self._text_reminder_sent = False  # Spam control
        self._prompt_message_id: Optional[int] = None  # Track prompt for keyboard removal

    def get_items(self) -> List[Tuple[str, str]]:
        """Get items - evaluates callable if dynamic."""
        if callable(self._items):
            return self._items(self.context)
        return self._items

    def _get_first_page_items(self) -> List[Tuple[str, str]]:
        """Get items for the first page (buttons)."""
        return self.get_items()[:self.page_size]

    def _get_remaining_items(self) -> List[Tuple[str, str]]:
        """Get items beyond the first page."""
        return self.get_items()[self.page_size:]

    def _has_more_items(self) -> bool:
        """Check if there are items beyond the first page."""
        return len(self.get_items()) > self.page_size

    def _build_error_response(self, remaining: List[Tuple[str, str]]) -> DialogResponse:
        """Build error response for invalid text input.

        Args:
            remaining: List of remaining items to display.

        Returns:
            DialogResponse with error message and re-prompt.
        """
        lines = [f"{i + 1}. {label}" for i, (label, _) in enumerate(remaining)]
        error_text = f"Please enter a number between 1 and {len(remaining)}.\n\n"
        text_prompt = f"{self.prompt}\n\n" + "\n".join(lines) + "\n\nEnter the number of your choice:"

        keyboard = None
        if self.include_cancel:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
            ])

        return DialogResponse(
            text=error_text + text_prompt,
            keyboard=keyboard,
            edit_message=False,
        )

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        """Stop polling when dialog is complete."""
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        callback_query = update.callback_query
        if callback_query is None or callback_query.data is None:
            return
        # Answer callback and remove keyboard
        await get_app().send_messages(TelegramCallbackAnswerMessage(callback_query.id))

        if callback_query.message:
            await get_app().send_messages(
                TelegramRemoveKeyboardMessage(callback_query.message.message_id)
            )

        # Delegate to dialog's handle_callback
        response = self.handle_callback(callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """Handle text input - only valid when showing more items."""
        if update.message is None or update.message.text is None:
            return

        if not self._showing_more:
            # Not in text input mode - remind user to use buttons
            if self.is_active and not self._text_reminder_sent:
                self._text_reminder_sent = True
                await get_app().send_messages("Please use the buttons to make a selection.")
            return

        text = update.message.text.strip()
        response = self.handle_text_input(text)

        # Remove keyboard from previous prompt
        if self._prompt_message_id is not None:
            await get_app().send_messages(TelegramRemoveKeyboardMessage(self._prompt_message_id))
            self._prompt_message_id = None

        if response:
            await self._send_response(response)

    def _get_poll_result(self) -> Any:
        """Return the dialog result after polling completes."""
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return

        if response.keyboard:
            msg = TelegramOptionsMessage(response.text, response.keyboard)
            await get_app().send_messages(msg)
            # Track message ID for later keyboard removal
            if msg.sent_message:
                self._prompt_message_id = msg.sent_message.message_id
        else:
            await get_app().send_messages(response.text)

    async def _run_dialog(self) -> DialogResult:
        """Send prompt with keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._showing_more = False
        self._text_reminder_sent = False  # Reset spam control

        # Send initial message with keyboard
        response = DialogResponse(
            text=self.prompt,
            keyboard=self._build_keyboard(),
            edit_message=False,
        )
        await self._send_response(response)

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle button press - set value and complete, or show more items."""
        if callback_data == self.CANCEL_CALLBACK:
            return self.cancel()

        if callback_data == self.MORE_CALLBACK:
            # Switch to text input mode for remaining items
            self._showing_more = True
            self.state = DialogState.AWAITING_TEXT

            # Build numbered list of remaining items
            remaining = self._get_remaining_items()
            lines = [f"{i + 1}. {label}" for i, (label, _) in enumerate(remaining)]
            text = f"{self.prompt}\n\n" + "\n".join(lines) + "\n\nEnter the number of your choice:"

            keyboard = None
            if self.include_cancel:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
                ])

            get_logger().info("InlineKeyboardPaginatedChoiceDialog.handle_callback: showing_more remaining_count=%d", len(remaining))

            return DialogResponse(
                text=text,
                keyboard=keyboard,
                edit_message=False,
            )

        # Verify callback is valid (from first page)
        valid_callbacks = [cb for _, cb in self._get_first_page_items()]
        if callback_data not in valid_callbacks:
            return None  # Unknown callback

        self._value = callback_data
        self.state = DialogState.COMPLETE

        # Find the label for the selected choice
        label = next((lbl for lbl, cb in self.get_items() if cb == callback_data), callback_data)

        # Log selection
        get_logger().info("InlineKeyboardPaginatedChoiceDialog.handle_callback: selected label=%s value=%s", label, callback_data)

        # Only send confirmation message if debug mode is enabled
        if DIALOG_DEBUG:
            return DialogResponse(
                text=f"Selected: {label}",
                keyboard=None,
                edit_message=False,
            )
        return DialogResponse.NO_CHANGE

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Handle text input when in 'showing more' mode."""
        if not self._showing_more:
            return None

        remaining = self._get_remaining_items()

        # Try to parse as number
        try:
            choice_num = int(text)
        except ValueError:
            # Re-prompt with error
            return self._build_error_response(remaining)

        # Validate range
        if choice_num < 1 or choice_num > len(remaining):
            return self._build_error_response(remaining)

        # Valid choice - get the selected item
        selected_label, selected_callback = remaining[choice_num - 1]
        self._value = selected_callback
        self.state = DialogState.COMPLETE

        # Log selection
        get_logger().info(
            "InlineKeyboardPaginatedChoiceDialog.handle_text_input: selected label=%s value=%s",
            selected_label,
            selected_callback,
        )

        # Only send confirmation message if debug mode is enabled
        if DIALOG_DEBUG:
            return DialogResponse(
                text=f"Selected: {selected_label}",
                keyboard=None,
                edit_message=False,
            )
        return DialogResponse.NO_CHANGE

    def _build_keyboard(self) -> InlineKeyboardMarkup:
        """Build keyboard from first page items, plus More and Cancel buttons."""
        buttons = [
            [InlineKeyboardButton(label, callback_data=callback)]
            for label, callback in self._get_first_page_items()
        ]
        if self._has_more_items():
            buttons.append([InlineKeyboardButton(self.more_label, callback_data=self.MORE_CALLBACK)])
        if self.include_cancel:
            buttons.append([InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)])
        return InlineKeyboardMarkup(buttons)

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._showing_more = False
        self._text_reminder_sent = False
        self._prompt_message_id = None


class UserInputDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User enters text.

    Optionally validates input before accepting.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_CALLBACK = "__cancel__"

    def __init__(
        self,
        prompt: Union[str, Callable[[], str]],
        validator: Optional[Callable[[str], Tuple[bool, str]]] = None,
        include_cancel: bool = True,
    ) -> None:
        """Create a text input dialog.

        Args:
            prompt: The question text to display or a callable that returns it.
            validator: Optional callable(text) -> (is_valid, error_message).
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self._prompt: Callable[[], str]
        self.prompt = prompt
        self.validator = validator
        self.include_cancel = include_cancel
        self._prompt_message_id: Optional[int] = None  # Track prompt message for keyboard removal

    @property
    def prompt(self) -> str:
        """Resolved prompt text for this dialog."""
        return self._prompt()

    @prompt.setter
    def prompt(self, value: Union[str, Callable[[], str]]) -> None:
        """Set prompt as a string or callable returning a string."""
        if callable(value):
            self._prompt = value
        else:
            self._prompt = lambda: value

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        callback_query = update.callback_query
        if callback_query is None or callback_query.data is None:
            return
        # Answer callback and remove keyboard
        await get_app().send_messages(TelegramCallbackAnswerMessage(callback_query.id))

        if callback_query.message:
            await get_app().send_messages(
                TelegramRemoveKeyboardMessage(callback_query.message.message_id)
            )

        # Delegate to dialog's handle_callback
        response = self.handle_callback(callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """Delegate to handle_text_input() and remove keyboard from previous prompt."""
        if update.message is None or update.message.text is None:
            return
        text = update.message.text.strip()
        response = self.handle_text_input(text)

        # Remove keyboard from previous prompt (whether valid or validation error)
        if self._prompt_message_id is not None:
            await get_app().send_messages(TelegramRemoveKeyboardMessage(self._prompt_message_id))
            self._prompt_message_id = None

        if response:
            await self._send_response(response)

    def _get_poll_result(self) -> Any:
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return

        if response.keyboard:
            msg = TelegramOptionsMessage(response.text, response.keyboard)
            await get_app().send_messages(msg)
            # Track message ID for later keyboard removal
            if msg.sent_message:
                self._prompt_message_id = msg.sent_message.message_id
        else:
            await get_app().send_messages(response.text)

    async def _run_dialog(self) -> DialogResult:
        """Show prompt and poll until text input received."""
        self.state = DialogState.AWAITING_TEXT

        keyboard = None
        if self.include_cancel:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
            ])
        response = DialogResponse(
            text=self.prompt,
            keyboard=keyboard,
            edit_message=False,
        )
        await self._send_response(response)

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle cancel button."""
        if callback_data == self.CANCEL_CALLBACK:
            return self.cancel()
        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Validate and accept text input."""
        if self.state != DialogState.AWAITING_TEXT:
            return None

        # Validate if validator provided
        if self.validator:
            is_valid, error_msg = self.validator(text)
            if not is_valid:
                # Re-show prompt with error
                keyboard = None
                if self.include_cancel:
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
                    ])
                return DialogResponse(
                    text=f"{error_msg}\n\n{self.prompt}",
                    keyboard=keyboard,
                    edit_message=False,
                )

        self._value = text
        self.state = DialogState.COMPLETE

        # Log input
        text_preview = text[:50] if len(text) > 50 else text
        get_logger().info("UserInputDialog.handle_text_input: received text=%s", text_preview)

        # Only send confirmation message if debug mode is enabled
        if DIALOG_DEBUG:
            return DialogResponse(
                text=f"Received: {text}",
                keyboard=None,
                edit_message=False,
            )
        return DialogResponse.NO_CHANGE

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._prompt_message_id = None


class InlineKeyboardConfirmDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: Yes/No confirmation prompt using inline keyboard.

    Convenience dialog for common Yes/No flows.
    Uses inline keyboard buttons that send callback_query events.
    Inherits UpdatePollerMixin for self-polling.
    """

    YES_CALLBACK = "__yes__"
    NO_CALLBACK = "__no__"
    CANCEL_CALLBACK = "__cancel__"

    def __init__(
        self,
        prompt: str,
        yes_label: str = "Yes",
        no_label: str = "No",
        include_cancel: bool = False,
    ) -> None:
        """Create a confirmation dialog.

        Args:
            prompt: The question text to display.
            yes_label: Label for the Yes button.
            no_label: Label for the No button.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        self.yes_label = yes_label
        self.no_label = no_label
        self.include_cancel = include_cancel
        self._text_reminder_sent = False  # Spam control

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        callback_query = update.callback_query
        if callback_query is None or callback_query.data is None:
            return
        # Answer callback and remove keyboard
        await get_app().send_messages(TelegramCallbackAnswerMessage(callback_query.id))

        if callback_query.message:
            await get_app().send_messages(
                TelegramRemoveKeyboardMessage(callback_query.message.message_id)
            )

        # Delegate to dialog's handle_callback
        response = self.handle_callback(callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """ConfirmDialog ignores text - clarify to user (once per activation)."""
        if self.is_active and not self._text_reminder_sent:
            self._text_reminder_sent = True
            await get_app().send_messages("Please use the buttons to make a selection.")

    def _get_poll_result(self) -> Any:
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return

        if response.keyboard:
            await get_app().send_messages(TelegramOptionsMessage(response.text, response.keyboard))
        else:
            await get_app().send_messages(response.text)

    async def _run_dialog(self) -> DialogResult:
        """Show prompt with Yes/No buttons, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._text_reminder_sent = False  # Reset spam control

        buttons = [
            [
                InlineKeyboardButton(self.yes_label, callback_data=self.YES_CALLBACK),
                InlineKeyboardButton(self.no_label, callback_data=self.NO_CALLBACK),
            ]
        ]
        if self.include_cancel:
            buttons.append([InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)])

        response = DialogResponse(
            text=self.prompt,
            keyboard=InlineKeyboardMarkup(buttons),
            edit_message=False,
        )
        await self._send_response(response)

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle Yes/No/Cancel button press."""
        if callback_data == self.CANCEL_CALLBACK:
            return self.cancel()

        if callback_data == self.YES_CALLBACK:
            self._value = True
            self.state = DialogState.COMPLETE
            get_logger().info("InlineKeyboardConfirmDialog.handle_callback: selected value=True label=%s", self.yes_label)
            if DIALOG_DEBUG:
                return DialogResponse(
                    text=f"{self.yes_label}",
                    keyboard=None,
                    edit_message=False,
                )
            return DialogResponse.NO_CHANGE

        if callback_data == self.NO_CALLBACK:
            self._value = False
            self.state = DialogState.COMPLETE
            get_logger().info("InlineKeyboardConfirmDialog.handle_callback: selected value=False label=%s", self.no_label)
            if DIALOG_DEBUG:
                return DialogResponse(
                    text=f"{self.no_label}",
                    keyboard=None,
                    edit_message=False,
                )
            return DialogResponse.NO_CHANGE

        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Confirm dialogs don't accept text - return None."""
        return None


# =============================================================================
# COMPOSITE DIALOGS
# =============================================================================

class SequenceDialog(Dialog):
    """Composite dialog: Run child dialogs in sequence.

    Supports named dialogs for easy value access:
    - SequenceDialog([dialog1, dialog2])  # Anonymous, indexed access
    - SequenceDialog([("name", dialog), ("age", dialog)])  # Named access

    Updates shared context as each dialog completes.
    Does NOT poll - delegates to children.
    """

    def __init__(
        self,
        dialogs: List[Union[Dialog, Tuple[str, Dialog]]],
    ) -> None:
        """Create a sequence dialog.

        Args:
            dialogs: List of dialogs or (name, dialog) tuples.
        """
        super().__init__()
        # Normalize to list of (name, dialog) tuples
        self._dialogs: List[Tuple[str, Dialog]] = []
        for i, item in enumerate(dialogs):
            if isinstance(item, tuple):
                name, dialog = item
                self._dialogs.append((name, dialog))
            else:
                self._dialogs.append((f"step_{i}", item))
        self._current_index = 0

    @property
    def current_dialog(self) -> Optional[Dialog]:
        """Get the currently active child dialog."""
        if self._current_index < len(self._dialogs):
            return self._dialogs[self._current_index][1]
        return None

    @property
    def values(self) -> Dict[str, Any]:
        """Named values dict: {name: dialog.value}"""
        return {name: d.value for name, d in self._dialogs}

    def build_result(self) -> DialogResult:
        """Sequence returns dict of named child results."""
        return {name: d.build_result() for name, d in self._dialogs}

    async def _run_dialog(self) -> DialogResult:
        """Run each child's start() in sequence."""
        self.state = DialogState.ACTIVE
        self._current_index = 0

        if not self._dialogs:
            self.state = DialogState.COMPLETE
            return {}

        for name, dialog in self._dialogs:
            # Pass our context to child - child's start() handles reset internally
            result = await dialog.start(self.context)
            self.context[name] = result
            self._current_index += 1

            if result is CANCELLED:
                self._value = CANCELLED
                self.state = DialogState.COMPLETE
                return CANCELLED

        self._value = self.values
        self.state = DialogState.COMPLETE
        return self.build_result()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to current child dialog (for backwards compatibility)."""
        current = self.current_dialog
        if current is None:
            return None
        return current.handle_callback(callback_data)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to current child dialog (for backwards compatibility)."""
        current = self.current_dialog
        if current is None:
            return None
        return current.handle_text_input(text)

    def reset(self) -> None:
        """Reset sequence and all child dialogs."""
        super().reset()
        self._current_index = 0
        for _, dialog in self._dialogs:
            dialog.reset()


class BranchDialog(Dialog):
    """Composite dialog: Condition-based branching.

    Evaluates a condition function on start to select which branch to run.
    Does NOT poll - delegates to selected branch.
    """

    def __init__(
        self,
        condition: Callable[[Dict[str, Any]], str],
        branches: Dict[str, Dialog],
    ) -> None:
        """Create a branch dialog.

        Args:
            condition: Callable(context) -> branch_key
            branches: Dict mapping branch keys to dialogs
        """
        super().__init__()
        self.condition = condition
        self.branches = branches
        self._active_branch: Optional[Dialog] = None
        self._active_key: Optional[str] = None

    def build_result(self) -> DialogResult:
        """Branch returns {selected_key: branch_result}."""
        if self._active_key and self._active_branch:
            return {self._active_key: self._active_branch.build_result()}
        return None

    async def _run_dialog(self) -> DialogResult:
        """Evaluate condition and run selected branch."""
        self.state = DialogState.ACTIVE

        # Evaluate condition to select branch
        branch_key = self.condition(self.context)

        if branch_key not in self.branches:
            logger = get_logger()
            logger.error("BranchDialog._run_dialog: key_not_found key=%s", branch_key)
            self._value = CANCELLED
            self.state = DialogState.COMPLETE
            return CANCELLED

        self._active_key = branch_key
        self._active_branch = self.branches[branch_key]

        # Child's start() handles reset and context internally
        result = await self._active_branch.start(self.context)
        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to active branch (for backwards compatibility)."""
        if self._active_branch is None:
            return None
        return self._active_branch.handle_callback(callback_data)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to active branch (for backwards compatibility)."""
        if self._active_branch is None:
            return None
        return self._active_branch.handle_text_input(text)

    def reset(self) -> None:
        """Reset branch dialog."""
        super().reset()
        self._active_branch = None
        self._active_key = None
        for dialog in self.branches.values():
            dialog.reset()


class InlineKeyboardChoiceBranchDialog(Dialog, UpdatePollerMixin):
    """Hybrid dialog: User selects branch via inline keyboard, then delegates.

    Shows a prompt with inline keyboard buttons, each button leads to a
    different dialog branch. Uses callback_query events for selection.
    Inherits UpdatePollerMixin to poll for the branch selection.
    """

    CANCEL_CALLBACK = "__cancel__"

    def __init__(
        self,
        prompt: str,
        branches: Dict[str, Tuple[str, Dialog]],
        include_cancel: bool = True,
    ) -> None:
        """Create a choice-branch dialog.

        Args:
            prompt: The question text to display.
            branches: Dict mapping keys to (label, dialog) tuples.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        self.branches = branches
        self.include_cancel = include_cancel
        self._active_branch: Optional[Dialog] = None
        self._active_key: Optional[str] = None
        self._choosing = True  # True while showing choice, False when running branch

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return not self._choosing  # Stop when branch selected

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        callback_query = update.callback_query
        if callback_query is None or callback_query.data is None:
            return
        # Answer callback and remove keyboard
        await get_app().send_messages(TelegramCallbackAnswerMessage(callback_query.id))

        if callback_query.message:
            await get_app().send_messages(
                TelegramRemoveKeyboardMessage(callback_query.message.message_id)
            )

        # Delegate to dialog's handle_callback
        response = self.handle_callback(callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """ChoiceBranchDialog ignores text while choosing."""
        pass  # Ignore text during branch selection

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return

        if response.keyboard:
            await get_app().send_messages(TelegramOptionsMessage(response.text, response.keyboard))
        else:
            await get_app().send_messages(response.text)

    def build_result(self) -> DialogResult:
        """Choice branch returns {selected_key: branch_result}."""
        if self._active_key and self._active_branch:
            return {self._active_key: self._active_branch.build_result()}
        return None

    def _get_poll_result(self) -> Any:
        """Return the value after polling (for cancel detection)."""
        return self.value  # Don't use build_result() - only need raw value for cancel check

    async def _run_dialog(self) -> DialogResult:
        """Show choice, poll for selection, then run selected branch."""
        self.state = DialogState.ACTIVE
        self._choosing = True
        self._active_branch = None
        self._active_key = None

        response = DialogResponse(
            text=self.prompt,
            keyboard=self._build_keyboard(),
            edit_message=False,
        )
        await self._send_response(response)

        # Poll until user selects a branch
        poll_result = await self.poll()

        if poll_result is CANCELLED:
            self.state = DialogState.COMPLETE
            return CANCELLED

        # Run selected branch - child's start() handles reset internally
        if self._active_branch is None:
            self._value = CANCELLED
            self.state = DialogState.COMPLETE
            return CANCELLED
        result = await self._active_branch.start(self.context)
        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle branch selection or delegate to active branch."""
        if self._choosing:
            # User is selecting a branch
            if callback_data == self.CANCEL_CALLBACK:
                return self.cancel()

            if callback_data not in self.branches:
                return None

            # Select the branch (don't start it - _run_dialog will do that)
            self._active_key = callback_data
            label, dialog = self.branches[callback_data]
            self._active_branch = dialog
            self._choosing = False

            # Log selection
            get_logger().info("InlineKeyboardChoiceBranchDialog.handle_callback: selected key=%s label=%s", callback_data, label)

            if DIALOG_DEBUG:
                return DialogResponse(
                    text=f"Selected: {label}",
                    keyboard=None,
                    edit_message=False,
                )
            return DialogResponse.NO_CHANGE

        # Delegate to active branch (for backwards compatibility)
        if self._active_branch is None:
            return None
        return self._active_branch.handle_callback(callback_data)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to active branch if running (for backwards compatibility)."""
        if self._choosing:
            return None  # Not accepting text while choosing

        if self._active_branch is None:
            return None
        return self._active_branch.handle_text_input(text)

    def _build_keyboard(self) -> InlineKeyboardMarkup:
        """Build keyboard from branches."""
        buttons = [
            [InlineKeyboardButton(label, callback_data=key)]
            for key, (label, _) in self.branches.items()
        ]
        if self.include_cancel:
            buttons.append([InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)])
        return InlineKeyboardMarkup(buttons)

    def reset(self) -> None:
        """Reset choice-branch dialog."""
        super().reset()
        self._active_branch = None
        self._active_key = None
        self._choosing = True
        for label, dialog in self.branches.values():
            dialog.reset()


class LoopDialog(Dialog):
    """Composite dialog: Repeat a dialog until exit condition.

    Runs the inner dialog repeatedly until:
    - value is CANCELLED, OR
    - value == exit_value, OR
    - exit_condition(value) returns True, OR
    - max_iterations reached

    Does NOT poll - delegates to inner dialog.
    """

    def __init__(
        self,
        dialog: Dialog,
        exit_value: Optional[Any] = None,
        exit_condition: Optional[Callable[[Any], bool]] = None,
        max_iterations: Optional[int] = None,
    ) -> None:
        """Create a loop dialog.

        Args:
            dialog: The dialog to repeat.
            exit_value: Exit when dialog.value == this value.
            exit_condition: Exit when this callable returns True.
            max_iterations: Maximum number of iterations (safety limit).
        """
        super().__init__()
        self.dialog = dialog
        self.exit_value = exit_value
        self.exit_condition = exit_condition
        self.max_iterations = max_iterations
        self._iterations = 0
        self._all_values: List[Any] = []

    def build_result(self) -> DialogResult:
        """Loop returns final value only."""
        return self.value

    def _should_exit(self, result: Any) -> bool:
        """Check if the loop should exit based on result."""
        if result is CANCELLED:
            return True
        if self.exit_value is not None and result == self.exit_value:
            return True
        if self.exit_condition is not None and self.exit_condition(result):
            return True
        if self.max_iterations is not None and self._iterations >= self.max_iterations:
            return True
        return False

    async def _run_dialog(self) -> DialogResult:
        """Run inner dialog repeatedly until exit condition."""
        self.state = DialogState.ACTIVE
        self._iterations = 0
        self._all_values = []

        while True:
            # Child's start() handles reset internally - no need to call reset() here
            result = await self.dialog.start(self.context)

            if result is CANCELLED:
                self._value = CANCELLED
                self.state = DialogState.COMPLETE
                return CANCELLED

            self._all_values.append(result)
            self._iterations += 1

            if self._should_exit(result):
                self._value = result
                self.state = DialogState.COMPLETE
                return self.build_result()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to inner dialog (for backwards compatibility)."""
        return self.dialog.handle_callback(callback_data)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to inner dialog (for backwards compatibility)."""
        return self.dialog.handle_text_input(text)

    def reset(self) -> None:
        """Reset loop dialog."""
        super().reset()
        self._iterations = 0
        self._all_values = []
        self.dialog.reset()


class DialogHandler(Dialog):
    """Composite dialog: Wraps a dialog, runs it, calls on_complete.

    Does NOT poll - delegates to inner dialog.
    Provides a hook to process results after dialog completion.
    """

    def __init__(
        self,
        dialog: Dialog,
        on_complete: Optional[Callable[[DialogResult], Any]] = None,
    ) -> None:
        """Create a dialog handler.

        Args:
            dialog: The dialog to wrap.
            on_complete: Optional callback to call with the result.
                         Can be sync or async.
        """
        super().__init__()
        self.dialog = dialog
        self.on_complete = on_complete

    def build_result(self) -> DialogResult:
        """Handler returns inner dialog's result."""
        return self.dialog.build_result()

    async def _run_dialog(self) -> DialogResult:
        """Run inner dialog and call on_complete handler."""
        # Child's start() handles reset and context internally
        result = await self.dialog.start(self.context)

        # Always call on_complete, even if cancelled - let the callback decide how to handle it
        if self.on_complete:
            maybe_awaitable = self.on_complete(result)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to inner dialog (for backwards compatibility)."""
        return self.dialog.handle_callback(callback_data)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to inner dialog (for backwards compatibility)."""
        return self.dialog.handle_text_input(text)

    def reset(self) -> None:
        """Reset handler and inner dialog."""
        super().reset()
        self.dialog.reset()


class EditEventDialog(Dialog):
    """Dialog for editing an event's editable attributes via inline keyboard.

    Delegates to ChoiceDialog for field selection and boolean fields,
    and UserInputDialog for text fields. Does not poll directly.

    Shows a list of editable fields as buttons. Supports:
    - Boolean fields: Toggle buttons [True] [False] via ChoiceDialog
    - Other fields: Text input via UserInputDialog

    Edits are staged in the context and only applied when clicking Done.
    Supports optional cross-field validation after each field edit.

    Example:
        def validate_range(context):
            min_val = context.get("condition.limit_min", event.get("condition.limit_min"))
            max_val = context.get("condition.limit_max", event.get("condition.limit_max"))
            if min_val is not None and max_val is not None and min_val >= max_val:
                return False, "limit_min must be < limit_max"
            return True, ""

        dialog = EditEventDialog(my_event, validator=validate_range)
    """

    DONE_VALUE = "__done__"

    def __init__(
        self,
        event: "ActivateOnConditionEvent",
        validator: Optional[Callable[[Dict[str, Any]], Tuple[bool, str]]] = None,
    ) -> None:
        """Create an edit event dialog.

        Args:
            event: The event with editable_attributes to edit.
            validator: Optional cross-field validation function.
                Receives context dict with staged edits, returns (is_valid, error_msg).
                Called after each successful field edit.
        """
        super().__init__()
        self.event = event
        self.validator = validator

    def _is_bool_field(self, attr: "EditableAttribute") -> bool:
        """Check if an attribute is a boolean type."""
        if attr.field_type == bool:
            return True
        if isinstance(attr.field_type, tuple) and bool in attr.field_type:
            return True
        return False

    def _get_field_display_value(self, field_name: str) -> str:
        """Get the display value for a field (from context or event)."""
        if field_name in self.context:
            return str(self.context[field_name])
        return str(self.event.get(field_name))

    def _build_field_choices(self, context: Dict[str, Any]) -> List[Tuple[str, str]]:
        """Build choices list for field selection dialog.

        Args:
            context: Dialog context (passed by ChoiceDialog, uses self.context instead).
        """
        # Note: We use self.context (which has staged edits) rather than the passed context
        choices = []
        for name in self.event.editable_attributes:
            display_value = self._get_field_display_value(name)
            label = f"{name}: {display_value}"
            choices.append((label, name))
        choices.append(("Done", self.DONE_VALUE))
        return choices

    def _get_field_list_prompt(self) -> str:
        """Build the prompt text for field list screen."""
        event_name = self.event.event_name
        return f'Editing "{event_name}". Select field:'

    def _validate_and_stage_value(
        self,
        field_name: str,
        parsed_value: Any,
    ) -> Tuple[bool, Optional[str]]:
        """Validate a parsed value and stage it in context if valid.

        Args:
            field_name: Name of the field being edited.
            parsed_value: The parsed value to validate and stage.

        Returns:
            (success, error_message) - error_message is None on success.
        """
        attr = self.event.editable_attributes[field_name]

        # Single-field validation
        is_valid, error = attr.validate(parsed_value)
        if not is_valid:
            return False, error

        # Tentatively stage the value
        old_value = self.context.get(field_name)
        self.context[field_name] = parsed_value

        # Cross-field validation (if validator provided)
        if self.validator:
            is_valid, error = self.validator(self.context)
            if not is_valid:
                # Revert the staged value
                if old_value is not None:
                    self.context[field_name] = old_value
                else:
                    del self.context[field_name]
                return False, error

        return True, None

    def _apply_all_edits(self) -> None:
        """Apply all staged edits to the event."""
        for field_name, value in self.context.items():
            self.event.edit(field_name, value)
        self.event.edited = True

    async def _edit_bool_field(self, field_name: str) -> bool:
        """Edit a boolean field using ConfirmDialog.

        Args:
            field_name: Name of the boolean field to edit.

        Returns:
            True if field was successfully edited, False if cancelled.
        """
        logger = get_logger()
        current = self._get_field_display_value(field_name)

        while True:
            bool_dialog = InlineKeyboardConfirmDialog(
                prompt=f"Set {field_name} to True? (current: {current})",
                yes_label="True",
                no_label="False",
                include_cancel=True,
            )
            result = await bool_dialog.start(self.context)

            if is_cancelled(result):
                logger.info("EditEventDialog._edit_bool_field: cancelled field=%s", field_name)
                return False

            new_value = result  # ConfirmDialog returns bool directly
            success, error = self._validate_and_stage_value(field_name, new_value)

            if success:
                logger.info(
                    "EditEventDialog._edit_bool_field: staged field=%s value=%s",
                    field_name,
                    new_value,
                )
                return True

            # Validation failed - show error and loop to re-prompt
            logger.info(
                "EditEventDialog._edit_bool_field: validation_failed field=%s error=%s",
                field_name,
                error,
            )
            await get_app().send_messages(f"⚠️ {error}")
            # Loop continues with a new ChoiceDialog

    async def _edit_text_field(self, field_name: str) -> bool:
        """Edit a text field using UserInputDialog.

        Args:
            field_name: Name of the text field to edit.

        Returns:
            True if field was successfully edited, False if cancelled.
        """
        logger = get_logger()
        attr = self.event.editable_attributes[field_name]

        def make_validator():
            """Create a validator that parses and validates the input."""
            def validator(text: str) -> Tuple[bool, str]:
                # Parse the input
                try:
                    parsed_value = attr.parse(text)
                except (ValueError, TypeError) as e:
                    error = str(e) if str(e) else "Invalid input"
                    return False, error

                # Single-field validation
                is_valid, error = attr.validate(parsed_value)
                if not is_valid:
                    return False, error

                # Cross-field validation (tentatively stage)
                if self.validator:
                    old_value = self.context.get(field_name)
                    self.context[field_name] = parsed_value
                    is_valid, error = self.validator(self.context)
                    # Revert for now - will stage properly if dialog completes
                    if old_value is not None:
                        self.context[field_name] = old_value
                    else:
                        self.context.pop(field_name, None)
                    if not is_valid:
                        return False, error

                return True, ""
            return validator

        current = self._get_field_display_value(field_name)
        text_dialog = UserInputDialog(
            prompt=f"Enter new value for {field_name} (current: {current}):",
            validator=make_validator(),
            include_cancel=True,
        )
        result = await text_dialog.start(self.context)

        if is_cancelled(result):
            logger.info("EditEventDialog._edit_text_field: cancelled field=%s", field_name)
            return False

        # Parse and stage the value (validator already checked it's valid)
        # UserInputDialog returns str, but mypy sees DialogResult which is Union
        if not isinstance(result, str):
            return False
        parsed_value = attr.parse(result)
        self.context[field_name] = parsed_value
        logger.info(
            "EditEventDialog._edit_text_field: staged field=%s value=%s",
            field_name,
            parsed_value,
        )
        return True

    async def _run_dialog(self) -> DialogResult:
        """Run the edit dialog loop until Done or Cancel."""
        self.state = DialogState.ACTIVE
        logger = get_logger()

        while True:
            # Show field selection dialog
            field_dialog = InlineKeyboardChoiceDialog(
                prompt=self._get_field_list_prompt(),
                choices=self._build_field_choices,  # Dynamic choices
                include_cancel=True,
            )
            result = await field_dialog.start(self.context)

            if is_cancelled(result):
                # Cancel from field list - exit without applying edits
                self._value = CANCELLED
                self.state = DialogState.COMPLETE
                logger.info("EditEventDialog._run_dialog: cancelled")
                return CANCELLED

            if result == self.DONE_VALUE:
                # Done - apply all edits
                self._apply_all_edits()
                self._value = dict(self.context)
                self.state = DialogState.COMPLETE
                logger.info("EditEventDialog._run_dialog: done edits=%s", self.context)
                return self.build_result()

            # Field selected - edit it
            if not isinstance(result, str):
                continue
            field_name = result
            if field_name not in self.event.editable_attributes:
                continue

            attr = self.event.editable_attributes[field_name]

            if self._is_bool_field(attr):
                await self._edit_bool_field(field_name)
            else:
                await self._edit_text_field(field_name)

            # After editing (success or cancel), loop back to field list

    def build_result(self) -> DialogResult:
        """Return the context dict with all staged edits."""
        return self.value

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Not used - delegates to child dialogs."""
        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Not used - delegates to child dialogs."""
        return None

    def reset(self) -> None:
        """Reset the dialog for reuse."""
        super().reset()


# =============================================================================
# REPLY KEYBOARD DIALOGS
# =============================================================================

class ReplyKeyboardChoiceDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User selects from reply keyboard options.

    Alternative to InlineKeyboardChoiceDialog that uses Telegram's reply keyboard
    instead of inline keyboard. Reply keyboards appear at the bottom of the chat
    and send text messages when pressed.

    Supports static choices list or dynamic choices via callable.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str,
        choices: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]],
        include_cancel: bool = True,
    ) -> None:
        """Create a reply keyboard choice dialog.

        Args:
            prompt: The question text to display.
            choices: List of (label, callback_data) tuples, or callable(context) returning same.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt: str = prompt
        if callable(choices):
            sig = inspect.signature(choices)
            params = [p for p in sig.parameters.values() 
                      if p.default is inspect.Parameter.empty]
            assert len(params) == 1, (
                f"choices callable must accept exactly 1 argument (context), "
                f"got {len(params)} required parameters"
            )
        self._choices: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]] = choices
        self.include_cancel: bool = include_cancel
        self._label_to_callback: Dict[str, str] = {}

    def get_choices(self) -> List[Tuple[str, str]]:
        """Get choices - evaluates callable if dynamic."""
        if callable(self._choices):
            return self._choices(self.context)
        return self._choices

    def _build_label_mapping(self) -> None:
        """Build mapping from button labels to callback_data values."""
        self._label_to_callback = {label: callback for label, callback in self.get_choices()}

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        """Stop polling when dialog is complete."""
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Reply keyboard dialogs don't receive callbacks - ignore."""
        pass

    async def handle_text_update(self, update: Update) -> None:
        """Handle text input by matching against button labels."""
        if update.message is None or update.message.text is None:
            return

        text = update.message.text.strip()

        # Check for cancel
        if text == self.CANCEL_LABEL and self.include_cancel:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("Cancelled.")
            )
            self.cancel()
            return

        # Check if text matches a button label
        if text in self._label_to_callback:
            callback_data = self._label_to_callback[text]

            # Remove keyboard silently (empty message)
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("✓")
            )

            self._value = callback_data
            self.state = DialogState.COMPLETE

            # Log selection
            get_logger().info(
                "ReplyKeyboardChoiceDialog.handle_text_update: selected label=%s value=%s",
                text,
                callback_data,
            )

            # Only send confirmation message if debug mode is enabled
            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {text}")

    def _get_poll_result(self) -> Any:
        """Return the dialog result after polling completes."""
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _run_dialog(self) -> DialogResult:
        """Send prompt with reply keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE

        # Build label mapping
        self._build_label_mapping()

        # Build keyboard layout
        keyboard = self._build_keyboard()

        # Send message with reply keyboard
        await get_app().send_messages(
            TelegramReplyKeyboardMessage(
                text=self.prompt,
                keyboard=keyboard,
                one_time_keyboard=True,
            )
        )

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Reply keyboard dialogs don't handle callbacks - return None."""
        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Text input is handled via handle_text_update - return None."""
        return None

    def _build_keyboard(self) -> List[List[str]]:
        """Build reply keyboard layout from choices."""
        keyboard = [[label] for label, _ in self.get_choices()]
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])
        return keyboard

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._label_to_callback = {}


class ReplyKeyboardConfirmDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: Yes/No confirmation prompt using reply keyboard.

    Alternative to InlineKeyboardConfirmDialog that uses Telegram's reply keyboard
    instead of inline keyboard. Reply keyboards appear at the bottom of the chat
    and send text messages when pressed.

    Convenience dialog for common Yes/No flows.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str,
        yes_label: str = "Yes",
        no_label: str = "No",
        include_cancel: bool = False,
    ) -> None:
        """Create a reply keyboard confirmation dialog.
        
        Args:
            prompt: The question text to display.
            yes_label: Label for the Yes button.
            no_label: Label for the No button.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt: str = prompt
        self.yes_label: str = yes_label
        self.no_label: str = no_label
        self.include_cancel: bool = include_cancel

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        """Stop polling when dialog is complete."""
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Reply keyboard dialogs don't receive callbacks - ignore."""
        pass

    async def handle_text_update(self, update: Update) -> None:
        """Handle text input by matching against button labels."""
        if update.message is None or update.message.text is None:
            return

        text = update.message.text.strip()

        # Check for cancel
        if text == self.CANCEL_LABEL and self.include_cancel:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("Cancelled.")
            )
            self.cancel()
            return

        # Check for Yes
        if text == self.yes_label:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("✓")
            )
            self._value = True
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ReplyKeyboardConfirmDialog.handle_text_update: selected value=True label=%s",
                self.yes_label,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"{self.yes_label}")
            return

        # Check for No
        if text == self.no_label:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("✓")
            )
            self._value = False
            self.state = DialogState.COMPLETE
            get_logger().info(
                "ReplyKeyboardConfirmDialog.handle_text_update: selected value=False label=%s",
                self.no_label,
            )
            if DIALOG_DEBUG:
                await get_app().send_messages(f"{self.no_label}")
            return

    def _get_poll_result(self) -> Any:
        """Return the dialog result after polling completes."""
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _run_dialog(self) -> DialogResult:
        """Show prompt with Yes/No reply keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE

        # Build keyboard layout
        keyboard = [[self.yes_label, self.no_label]]
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])

        # Send message with reply keyboard
        await get_app().send_messages(
            TelegramReplyKeyboardMessage(
                text=self.prompt,
                keyboard=keyboard,
                one_time_keyboard=True,
            )
        )

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Reply keyboard dialogs don't handle callbacks - return None."""
        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Text input is handled via handle_text_update - return None."""
        return None


class ReplyKeyboardPaginatedChoiceDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User selects from a paginated list of reply keyboard options.

    Alternative to InlineKeyboardPaginatedChoiceDialog that uses Telegram's reply
    keyboard instead of inline keyboard.

    Shows first `page_size` items as buttons. If there are more items,
    shows a "More..." button. Clicking "More..." displays all remaining
    items as a numbered text list and prompts for text input.

    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_LABEL = "Cancel"
    MORE_LABEL = "More..."

    def __init__(
        self,
        prompt: str,
        items: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]],
        page_size: int = 5,
        more_label: str = "More...",
        include_cancel: bool = True,
    ) -> None:
        """Create a paginated reply keyboard choice dialog.

        Args:
            prompt: The question text to display.
            items: List of (label, callback_data) tuples, or callable(context) returning same.
            page_size: Number of items to show as buttons (default 5).
            more_label: Label for the "show more" button.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        if callable(items):
            sig = inspect.signature(items)
            params = [p for p in sig.parameters.values()
                      if p.default is inspect.Parameter.empty]
            assert len(params) == 1, (
                f"items callable must accept exactly 1 argument (context), "
                f"got {len(params)} required parameters"
            )
        self._items = items
        self.page_size = page_size
        self.more_label = more_label
        self.include_cancel = include_cancel
        self._showing_more = False  # True when in text input mode for remaining items
        self._label_to_callback: Dict[str, str] = {}

    def get_items(self) -> List[Tuple[str, str]]:
        """Get items - evaluates callable if dynamic."""
        if callable(self._items):
            return self._items(self.context)
        return self._items

    def _get_first_page_items(self) -> List[Tuple[str, str]]:
        """Get items for the first page (buttons)."""
        return self.get_items()[:self.page_size]

    def _get_remaining_items(self) -> List[Tuple[str, str]]:
        """Get items beyond the first page."""
        return self.get_items()[self.page_size:]

    def _has_more_items(self) -> bool:
        """Check if there are items beyond the first page."""
        return len(self.get_items()) > self.page_size

    def _build_label_mapping(self) -> None:
        """Build mapping from button labels to callback_data values for first page."""
        self._label_to_callback = {
            label: callback for label, callback in self._get_first_page_items()
        }

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        """Stop polling when dialog is complete."""
        return self.is_complete

    async def handle_callback_update(self, update: Update) -> None:
        """Reply keyboard dialogs don't receive callbacks - ignore."""
        pass

    async def handle_text_update(self, update: Update) -> None:
        """Handle text input by matching against button labels or number input."""
        if update.message is None or update.message.text is None:
            return

        text = update.message.text.strip()

        # Check for cancel
        if text == self.CANCEL_LABEL and self.include_cancel:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("Cancelled.")
            )
            self.cancel()
            return

        if self._showing_more:
            # In text input mode - expecting a number
            remaining = self._get_remaining_items()

            # Try to parse as number
            try:
                choice_num = int(text)
            except ValueError:
                # Re-prompt with error
                await self._send_more_error(remaining)
                return

            # Validate range
            if choice_num < 1 or choice_num > len(remaining):
                await self._send_more_error(remaining)
                return

            # Valid choice - get the selected item
            selected_label, selected_callback = remaining[choice_num - 1]

            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("✓")
            )

            self._value = selected_callback
            self.state = DialogState.COMPLETE

            get_logger().info(
                "ReplyKeyboardPaginatedChoiceDialog.handle_text_update: selected label=%s value=%s",
                selected_label,
                selected_callback,
            )

            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {selected_label}")
            return

        # Check for "More..." button
        if text == self.more_label and self._has_more_items():
            self._showing_more = True
            self.state = DialogState.AWAITING_TEXT

            # Build numbered list of remaining items
            remaining = self._get_remaining_items()
            lines = [f"{i + 1}. {label}" for i, (label, _) in enumerate(remaining)]
            msg_text = f"{self.prompt}\n\n" + "\n".join(lines) + "\n\nEnter the number of your choice:"

            # Build keyboard with just Cancel
            keyboard: List[List[str]] = []
            if self.include_cancel:
                keyboard.append([self.CANCEL_LABEL])

            await get_app().send_messages(
                TelegramReplyKeyboardMessage(
                    text=msg_text,
                    keyboard=keyboard if keyboard else [[self.CANCEL_LABEL]],
                    one_time_keyboard=False,  # Keep visible for cancel
                )
            )

            get_logger().info(
                "ReplyKeyboardPaginatedChoiceDialog.handle_text_update: showing_more remaining_count=%d",
                len(remaining),
            )
            return

        # Check if text matches a first page button label
        if text in self._label_to_callback:
            callback_data = self._label_to_callback[text]

            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("✓")
            )

            self._value = callback_data
            self.state = DialogState.COMPLETE

            get_logger().info(
                "ReplyKeyboardPaginatedChoiceDialog.handle_text_update: selected label=%s value=%s",
                text,
                callback_data,
            )

            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {text}")

    async def _send_more_error(self, remaining: List[Tuple[str, str]]) -> None:
        """Send error message when invalid number input in 'more' mode."""
        lines = [f"{i + 1}. {label}" for i, (label, _) in enumerate(remaining)]
        error_text = f"Please enter a number between 1 and {len(remaining)}.\n\n"
        text_prompt = f"{self.prompt}\n\n" + "\n".join(lines) + "\n\nEnter the number of your choice:"

        keyboard: List[List[str]] = []
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])

        await get_app().send_messages(
            TelegramReplyKeyboardMessage(
                text=error_text + text_prompt,
                keyboard=keyboard if keyboard else [[self.CANCEL_LABEL]],
                one_time_keyboard=False,
            )
        )

    def _get_poll_result(self) -> Any:
        """Return the dialog result after polling completes."""
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _run_dialog(self) -> DialogResult:
        """Send prompt with reply keyboard, then poll until selection made."""
        self.state = DialogState.ACTIVE
        self._showing_more = False

        # Build label mapping for first page
        self._build_label_mapping()

        # Build keyboard layout
        keyboard = self._build_keyboard()

        # Send message with reply keyboard
        await get_app().send_messages(
            TelegramReplyKeyboardMessage(
                text=self.prompt,
                keyboard=keyboard,
                one_time_keyboard=True,
            )
        )

        # Poll until complete
        return await self.poll()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Reply keyboard dialogs don't handle callbacks - return None."""
        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Text input is handled via handle_text_update - return None."""
        return None

    def _build_keyboard(self) -> List[List[str]]:
        """Build reply keyboard layout from first page items, plus More and Cancel."""
        keyboard = [[label] for label, _ in self._get_first_page_items()]
        if self._has_more_items():
            keyboard.append([self.more_label])
        if self.include_cancel:
            keyboard.append([self.CANCEL_LABEL])
        return keyboard

    def reset(self) -> None:
        """Reset dialog for reuse."""
        super().reset()
        self._showing_more = False
        self._label_to_callback = {}


class ReplyKeyboardChoiceBranchDialog(Dialog, UpdatePollerMixin):
    """Hybrid dialog: User selects branch via reply keyboard, then delegates.

    Alternative to InlineKeyboardChoiceBranchDialog that uses Telegram's reply
    keyboard instead of inline keyboard.

    Shows a prompt with reply keyboard buttons, each button leads to a
    different dialog branch.
    Inherits UpdatePollerMixin to poll for the branch selection.
    """

    CANCEL_LABEL = "Cancel"

    def __init__(
        self,
        prompt: str,
        branches: Dict[str, Tuple[str, Dialog]],
        include_cancel: bool = True,
    ) -> None:
        """Create a reply keyboard choice-branch dialog.

        Args:
            prompt: The question text to display.
            branches: Dict mapping keys to (label, dialog) tuples.
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt: str = prompt
        self.branches: Dict[str, Tuple[str, Dialog]] = branches
        self.include_cancel: bool = include_cancel
        self._active_branch: Optional[Dialog] = None
        self._active_key: Optional[str] = None
        self._choosing: bool = True  # True while showing choice, False when running branch
        self._label_to_key: Dict[str, str] = {}

    def _build_label_mapping(self) -> None:
        """Build mapping from button labels to branch keys."""
        self._label_to_key = {label: key for key, (label, _) in self.branches.items()}

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        """Stop polling when branch selected."""
        return not self._choosing

    async def handle_callback_update(self, update: Update) -> None:
        """Reply keyboard dialogs don't receive callbacks - ignore."""
        pass

    async def handle_text_update(self, update: Update) -> None:
        """Handle text input by matching against button labels."""
        if not self._choosing:
            return  # Delegate to branch

        if update.message is None or update.message.text is None:
            return

        text = update.message.text.strip()

        # Check for cancel
        if text == self.CANCEL_LABEL and self.include_cancel:
            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("Cancelled.")
            )
            self.cancel()
            self._choosing = False  # Stop polling
            return

        # Check if text matches a branch label
        if text in self._label_to_key:
            branch_key = self._label_to_key[text]

            await get_app().send_messages(
                TelegramRemoveReplyKeyboardMessage("✓")
            )

            # Select the branch (don't start it - _run_dialog will do that)
            self._active_key = branch_key
            _, dialog = self.branches[branch_key]
            self._active_branch = dialog
            self._choosing = False

            get_logger().info(
                "ReplyKeyboardChoiceBranchDialog.handle_text_update: selected key=%s label=%s",
                branch_key,
                text,
            )

            if DIALOG_DEBUG:
                await get_app().send_messages(f"Selected: {text}")

    def _get_poll_result(self) -> Any:
        """Return the value after polling (for cancel detection)."""
        return self.value  # Don't use build_result() - only need raw value for cancel check

    def build_result(self) -> DialogResult:
        """Choice branch returns {selected_key: branch_result}."""
        if self._active_key and self._active_branch:
            return {self._active_key: self._active_branch.build_result()}
        return None

    async def _run_dialog(self) -> DialogResult:
        """Show choice, poll for selection, then run selected branch."""
        self.state = DialogState.ACTIVE
        self._choosing = True
        self._active_branch = None
        self._active_key = None

        # Build label mapping
        self._build_label_mapping()

        # Build keyboard layout
        keyboard = self._build_keyboard()

        # Send message with reply keyboard
        await get_app().send_messages(
            TelegramReplyKeyboardMessage(
                text=self.prompt,
                keyboard=keyboard,
                one_time_keyboard=True,
            )
        )

        # Poll until user selects a branch
        poll_result = await self.poll()

        if poll_result is CANCELLED:
            self.state = DialogState.COMPLETE
            return CANCELLED

        # Run selected branch - child's start() handles reset internally
        if self._active_branch is None:
            self._value = CANCELLED
            self.state = DialogState.COMPLETE
            return CANCELLED
        result = await self._active_branch.start(self.context)
        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result()

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Reply keyboard dialogs don't handle callbacks - return None."""
        return None

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Text input is handled via handle_text_update - return None."""
        return None

    def _build_keyboard(self) -> List[List[str]]:
        """Build reply keyboard layout from branches."""
        keyboard = [[label] for _, (label, _) in self.branches.items()]
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
        for _, (_, dialog) in self.branches.items():
            dialog.reset()


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_choice_dialog(
    prompt: str,
    choices: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]],
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    include_cancel: bool = True,
) -> Dialog:
    """Create a choice dialog with specified keyboard type.

    Factory function that creates either an InlineKeyboardChoiceDialog or
    ReplyKeyboardChoiceDialog based on the keyboard_type parameter.

    Args:
        prompt: The question text to display.
        choices: List of (label, callback_data) tuples, or callable(context) returning same.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        include_cancel: If True, add a Cancel button.

    Returns:
        A ChoiceDialog instance of the appropriate type.
    """
    if keyboard_type == KeyboardType.REPLY:
        return ReplyKeyboardChoiceDialog(prompt, choices, include_cancel)
    return InlineKeyboardChoiceDialog(prompt, choices, include_cancel)


def create_confirm_dialog(
    prompt: str,
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    yes_label: str = "Yes",
    no_label: str = "No",
    include_cancel: bool = False,
) -> Dialog:
    """Create a confirmation dialog with specified keyboard type.

    Factory function that creates either an InlineKeyboardConfirmDialog or
    ReplyKeyboardConfirmDialog based on the keyboard_type parameter.

    Args:
        prompt: The question text to display.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        yes_label: Label for the Yes button.
        no_label: Label for the No button.
        include_cancel: If True, add a Cancel button.

    Returns:
        A ConfirmDialog instance of the appropriate type.
    """
    if keyboard_type == KeyboardType.REPLY:
        return ReplyKeyboardConfirmDialog(
            prompt,
            yes_label,
            no_label,
            include_cancel,
        )
    return InlineKeyboardConfirmDialog(
        prompt,
        yes_label,
        no_label,
        include_cancel,
    )


def create_paginated_choice_dialog(
    prompt: str,
    items: Union[List[Tuple[str, str]], Callable[[Dict[str, Any]], List[Tuple[str, str]]]],
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    page_size: int = 5,
    more_label: str = "More...",
    include_cancel: bool = True,
) -> Dialog:
    """Create a paginated choice dialog with specified keyboard type.

    Factory function that creates either an InlineKeyboardPaginatedChoiceDialog or
    ReplyKeyboardPaginatedChoiceDialog based on the keyboard_type parameter.

    Args:
        prompt: The question text to display.
        items: List of (label, callback_data) tuples, or callable(context) returning same.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        page_size: Number of items to show as buttons (default 5).
        more_label: Label for the "show more" button.
        include_cancel: If True, add a Cancel button.

    Returns:
        A PaginatedChoiceDialog instance of the appropriate type.
    """
    if keyboard_type == KeyboardType.REPLY:
        return ReplyKeyboardPaginatedChoiceDialog(
            prompt, items, page_size, more_label, include_cancel
        )
    return InlineKeyboardPaginatedChoiceDialog(
        prompt, items, page_size, more_label, include_cancel
    )


def create_choice_branch_dialog(
    prompt: str,
    branches: Dict[str, Tuple[str, Dialog]],
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    include_cancel: bool = True,
) -> Dialog:
    """Create a choice-branch dialog with specified keyboard type.

    Factory function that creates either an InlineKeyboardChoiceBranchDialog or
    ReplyKeyboardChoiceBranchDialog based on the keyboard_type parameter.

    Args:
        prompt: The question text to display.
        branches: Dict mapping keys to (label, dialog) tuples.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        include_cancel: If True, add a Cancel button.

    Returns:
        A ChoiceBranchDialog instance of the appropriate type.
    """
    if keyboard_type == KeyboardType.REPLY:
        return ReplyKeyboardChoiceBranchDialog(
            prompt,
            branches,
            include_cancel,
        )
    return InlineKeyboardChoiceBranchDialog(
        prompt,
        branches,
        include_cancel,
    )
