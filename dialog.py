"""Dialog system for interactive multi-step Telegram conversations.

This module implements the Composite pattern for building complex dialogs
from simple atomic components (leaf dialogs) and composites.

Leaf dialogs (one question each):
- ChoiceDialog: User selects from keyboard options
- UserInputDialog: User enters text
- ConfirmDialog: Yes/No prompt

Composite dialogs:
- SequenceDialog: Run dialogs in order
- BranchDialog: Condition-based branching
- ChoiceBranchDialog: User selects branch via keyboard
- LoopDialog: Repeat until exit condition
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update

from .accessors import get_bot, get_chat_id, get_logger
from .polling import UpdatePollerMixin
from .telegram_utilities import (
    TelegramMessage,
    TelegramTextMessage,
    TelegramOptionsMessage,
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
)


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
DialogResponse.NO_CHANGE = DialogResponse(text="", keyboard=None, edit_message=False)


class Dialog(ABC):
    """Base class for all dialogs (leaf and composite).
    
    All dialogs share:
    - state: Current DialogState
    - value: Result after completion
    - context: Shared dict for cross-dialog communication
    
    Methods:
    - start(context, update_offset): Async entry point, runs dialog until complete
    - _run_dialog(update_offset): Abstract method subclasses implement
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
        update_offset: int = 0,
    ) -> Tuple[DialogResult, int]:
        """Start and run the dialog until complete.
        
        Template method that:
        1. Calls reset() to ensure clean state
        2. Sets context from parameter (or empty dict)
        3. Calls _run_dialog() which subclasses implement
        
        Args:
            context: Optional shared context dict.
            update_offset: Telegram update offset to continue from.
            
        Returns:
            Tuple of (DialogResult, final_update_offset)
        """
        self.reset()
        self._context = context if context is not None else {}
        return await self._run_dialog(update_offset)

    @abstractmethod
    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
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
        logger.info("dialog_cancelled")
        return DialogResponse(text="Cancelled.", keyboard=None, edit_message=False)

    def reset(self) -> None:
        """Reset dialog for reuse (e.g., in LoopDialog)."""
        self.state = DialogState.INACTIVE
        self._value = None


# =============================================================================
# LEAF DIALOGS
# =============================================================================

class ChoiceDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User selects from keyboard options.
    
    Supports static choices list or dynamic choices via callable.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_CALLBACK = "__cancel__"

    def __init__(
        self,
        prompt: str,
        choices: Union[List[Tuple[str, str]], Callable[[Dict], List[Tuple[str, str]]]],
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

    def _get_bot(self) -> Bot:
        return get_bot()

    def _get_chat_id(self) -> str:
        return get_chat_id()

    def _get_logger(self) -> logging.Logger:
        return get_logger()

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        # Answer callback
        callback_answer = TelegramCallbackAnswerMessage(update.callback_query.id)
        await callback_answer.send(bot, chat_id, logger)
        
        # Remove keyboard from clicked message (scoped to this message only)
        if update.callback_query.message:
            remove_kb = TelegramRemoveKeyboardMessage(update.callback_query.message.message_id)
            await remove_kb.send(bot, chat_id, logger)
        
        # Delegate to dialog's handle_callback
        response = self.handle_callback(update.callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """ChoiceDialog ignores text - clarify to user (once per activation)."""
        if self.is_active and not self._text_reminder_sent:
            self._text_reminder_sent = True
            clarify = TelegramTextMessage("Please use the buttons to make a selection.")
            await clarify.send(self._get_bot(), self._get_chat_id(), self._get_logger())

    def _get_poll_result(self) -> Any:
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return
        
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        if response.keyboard:
            msg = TelegramOptionsMessage(response.text, response.keyboard)
        else:
            msg = TelegramTextMessage(response.text)
        await msg.send(bot, chat_id, logger)

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
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
        result, final_offset = await self.poll(update_offset)
        return result, final_offset

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
        logger = self._get_logger()
        logger.info("choice_dialog_selected label=%s value=%s", label, callback_data)
        
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


class UserInputDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: User enters text.
    
    Optionally validates input before accepting.
    Inherits UpdatePollerMixin for self-polling.
    """

    CANCEL_CALLBACK = "__cancel__"

    def __init__(
        self,
        prompt: str,
        validator: Optional[Callable[[str], Tuple[bool, str]]] = None,
        include_cancel: bool = True,
    ) -> None:
        """Create a text input dialog.
        
        Args:
            prompt: The question text to display.
            validator: Optional callable(text) -> (is_valid, error_message).
            include_cancel: If True, add a Cancel button.
        """
        super().__init__()
        self.prompt = prompt
        self.validator = validator
        self.include_cancel = include_cancel

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return self.is_complete

    def _get_bot(self) -> Bot:
        return get_bot()

    def _get_chat_id(self) -> str:
        return get_chat_id()

    def _get_logger(self) -> logging.Logger:
        return get_logger()

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        # Answer callback
        callback_answer = TelegramCallbackAnswerMessage(update.callback_query.id)
        await callback_answer.send(bot, chat_id, logger)
        
        # Remove keyboard from clicked message
        if update.callback_query.message:
            remove_kb = TelegramRemoveKeyboardMessage(update.callback_query.message.message_id)
            await remove_kb.send(bot, chat_id, logger)
        
        # Delegate to dialog's handle_callback
        response = self.handle_callback(update.callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """Delegate to handle_text_input()."""
        text = update.message.text.strip()
        response = self.handle_text_input(text)
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
        
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        if response.keyboard:
            msg = TelegramOptionsMessage(response.text, response.keyboard)
        else:
            msg = TelegramTextMessage(response.text)
        await msg.send(bot, chat_id, logger)

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
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
        result, final_offset = await self.poll(update_offset)
        return result, final_offset

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
        logger = self._get_logger()
        logger.info("user_input_dialog_received text=%s", text[:50] if len(text) > 50 else text)
        
        # Only send confirmation message if debug mode is enabled
        if DIALOG_DEBUG:
            return DialogResponse(
                text=f"Received: {text}",
                keyboard=None,
                edit_message=False,
            )
        return DialogResponse.NO_CHANGE


class ConfirmDialog(Dialog, UpdatePollerMixin):
    """Leaf dialog: Yes/No confirmation prompt.
    
    Convenience dialog for common Yes/No flows.
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

    def _get_bot(self) -> Bot:
        return get_bot()

    def _get_chat_id(self) -> str:
        return get_chat_id()

    def _get_logger(self) -> logging.Logger:
        return get_logger()

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        # Answer callback
        callback_answer = TelegramCallbackAnswerMessage(update.callback_query.id)
        await callback_answer.send(bot, chat_id, logger)
        
        # Remove keyboard from clicked message
        if update.callback_query.message:
            remove_kb = TelegramRemoveKeyboardMessage(update.callback_query.message.message_id)
            await remove_kb.send(bot, chat_id, logger)
        
        # Delegate to dialog's handle_callback
        response = self.handle_callback(update.callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """ConfirmDialog ignores text - clarify to user (once per activation)."""
        if self.is_active and not self._text_reminder_sent:
            self._text_reminder_sent = True
            clarify = TelegramTextMessage("Please use the buttons to make a selection.")
            await clarify.send(self._get_bot(), self._get_chat_id(), self._get_logger())

    def _get_poll_result(self) -> Any:
        return self.build_result()

    def build_result(self) -> DialogResult:
        """Leaf returns raw value."""
        return self.value

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return
        
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        if response.keyboard:
            msg = TelegramOptionsMessage(response.text, response.keyboard)
        else:
            msg = TelegramTextMessage(response.text)
        await msg.send(bot, chat_id, logger)

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
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
        result, final_offset = await self.poll(update_offset)
        return result, final_offset

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle Yes/No/Cancel button press."""
        if callback_data == self.CANCEL_CALLBACK:
            return self.cancel()
        
        logger = self._get_logger()
        
        if callback_data == self.YES_CALLBACK:
            self._value = True
            self.state = DialogState.COMPLETE
            logger.info("confirm_dialog_selected value=True label=%s", self.yes_label)
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
            logger.info("confirm_dialog_selected value=False label=%s", self.no_label)
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

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
        """Run each child's start() in sequence."""
        self.state = DialogState.ACTIVE
        self._current_index = 0
        
        if not self._dialogs:
            self.state = DialogState.COMPLETE
            return {}, update_offset
        
        current_offset = update_offset
        for name, dialog in self._dialogs:
            # Pass our context to child - child's start() handles reset internally
            result, current_offset = await dialog.start(self.context, current_offset)
            self.context[name] = result
            self._current_index += 1
            
            if result is CANCELLED:
                self._value = CANCELLED
                self.state = DialogState.COMPLETE
                return CANCELLED, current_offset
        
        self._value = self.values
        self.state = DialogState.COMPLETE
        return self.build_result(), current_offset

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

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
        """Evaluate condition and run selected branch."""
        self.state = DialogState.ACTIVE
        
        # Evaluate condition to select branch
        branch_key = self.condition(self.context)
        
        if branch_key not in self.branches:
            logger = get_logger()
            logger.error("branch_key_not_found key=%s", branch_key)
            self._value = CANCELLED
            self.state = DialogState.COMPLETE
            return CANCELLED, update_offset
        
        self._active_key = branch_key
        self._active_branch = self.branches[branch_key]
        
        # Child's start() handles reset and context internally
        result, offset = await self._active_branch.start(self.context, update_offset)
        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result(), offset

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


class ChoiceBranchDialog(Dialog, UpdatePollerMixin):
    """Hybrid dialog: User selects branch (polls), then delegates to branch.
    
    Shows a prompt with buttons, each button leads to a different dialog branch.
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

    def _get_bot(self) -> Bot:
        return get_bot()

    def _get_chat_id(self) -> str:
        return get_chat_id()

    def _get_logger(self) -> logging.Logger:
        return get_logger()

    async def handle_callback_update(self, update: Update) -> None:
        """Answer callback, remove keyboard, delegate to handle_callback()."""
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        # Answer callback
        callback_answer = TelegramCallbackAnswerMessage(update.callback_query.id)
        await callback_answer.send(bot, chat_id, logger)
        
        # Remove keyboard from clicked message
        if update.callback_query.message:
            remove_kb = TelegramRemoveKeyboardMessage(update.callback_query.message.message_id)
            await remove_kb.send(bot, chat_id, logger)
        
        # Delegate to dialog's handle_callback
        response = self.handle_callback(update.callback_query.data)
        if response:
            await self._send_response(response)

    async def handle_text_update(self, update: Update) -> None:
        """ChoiceBranchDialog ignores text while choosing."""
        pass  # Ignore text during branch selection

    async def _send_response(self, response: DialogResponse) -> None:
        """Send a dialog response via Telegram."""
        if response is DialogResponse.NO_CHANGE:
            return
        
        bot = self._get_bot()
        chat_id = self._get_chat_id()
        logger = self._get_logger()
        
        if response.keyboard:
            msg = TelegramOptionsMessage(response.text, response.keyboard)
        else:
            msg = TelegramTextMessage(response.text)
        await msg.send(bot, chat_id, logger)

    def build_result(self) -> DialogResult:
        """Choice branch returns {selected_key: branch_result}."""
        if self._active_key and self._active_branch:
            return {self._active_key: self._active_branch.build_result()}
        return None

    def _get_poll_result(self) -> Any:
        """Return the value after polling (for cancel detection)."""
        return self.value  # Don't use build_result() - only need raw value for cancel check

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
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
        poll_result, current_offset = await self.poll(update_offset)
        
        if poll_result is CANCELLED:
            self.state = DialogState.COMPLETE
            return CANCELLED, current_offset
        
        # Run selected branch - child's start() handles reset internally
        result, final_offset = await self._active_branch.start(self.context, current_offset)
        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result(), final_offset

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
            logger = self._get_logger()
            logger.info("choice_branch_dialog_selected key=%s label=%s", callback_data, label)
            
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

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
        """Run inner dialog repeatedly until exit condition."""
        self.state = DialogState.ACTIVE
        self._iterations = 0
        self._all_values = []
        
        current_offset = update_offset
        while True:
            # Child's start() handles reset internally - no need to call reset() here
            result, current_offset = await self.dialog.start(self.context, current_offset)
            
            if result is CANCELLED:
                self._value = CANCELLED
                self.state = DialogState.COMPLETE
                return CANCELLED, current_offset
            
            self._all_values.append(result)
            self._iterations += 1
            
            if self._should_exit(result):
                self._value = result
                self.state = DialogState.COMPLETE
                return self.build_result(), current_offset

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

    async def _run_dialog(self, update_offset: int = 0) -> Tuple[DialogResult, int]:
        """Run inner dialog and call on_complete handler."""
        # Child's start() handles reset and context internally
        result, offset = await self.dialog.start(self.context, update_offset)
        
        # Always call on_complete, even if cancelled - let the callback decide how to handle it
        if self.on_complete:
            maybe_awaitable = self.on_complete(result)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable
        
        self._value = result
        self.state = DialogState.COMPLETE
        return self.build_result(), offset

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
