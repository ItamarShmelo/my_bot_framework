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

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .bot_application import get_logger


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
    - start(): Begin the dialog, return initial response
    - handle_callback(data): Handle button press
    - handle_text_input(text): Handle text input
    - cancel(): Cancel and complete with value=None
    - reset(): Reset for reuse (e.g., in LoopDialog)
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

    @abstractmethod
    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Start the dialog, return initial message with keyboard.
        
        Args:
            context: Optional shared context dict. If None, uses existing or empty dict.
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
        """Cancel dialog - sets value=None, state=COMPLETE."""
        self._value = None
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

class ChoiceDialog(Dialog):
    """Leaf dialog: User selects from keyboard options.
    
    Supports static choices list or dynamic choices via callable.
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

    def get_choices(self) -> List[Tuple[str, str]]:
        """Get choices - evaluates callable if dynamic."""
        if callable(self._choices):
            return self._choices(self.context)
        return self._choices

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Show prompt with keyboard built from choices."""
        if context is not None:
            self._context = context
        self.state = DialogState.ACTIVE
        return DialogResponse(
            text=self.prompt,
            keyboard=self._build_keyboard(),
            edit_message=False,
        )

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
        return DialogResponse(
            text=f"Selected: {label}",
            keyboard=None,
            edit_message=False,
        )

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


class UserInputDialog(Dialog):
    """Leaf dialog: User enters text.
    
    Optionally validates input before accepting.
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

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Show prompt and wait for text input."""
        if context is not None:
            self._context = context
        self.state = DialogState.AWAITING_TEXT
        keyboard = None
        if self.include_cancel:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)]
            ])
        return DialogResponse(
            text=self.prompt,
            keyboard=keyboard,
            edit_message=False,
        )

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
        return DialogResponse(
            text=f"Received: {text}",
            keyboard=None,
            edit_message=False,
        )


class ConfirmDialog(Dialog):
    """Leaf dialog: Yes/No confirmation prompt.
    
    Convenience dialog for common Yes/No flows.
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

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Show prompt with Yes/No buttons."""
        if context is not None:
            self._context = context
        self.state = DialogState.ACTIVE
        buttons = [
            [
                InlineKeyboardButton(self.yes_label, callback_data=self.YES_CALLBACK),
                InlineKeyboardButton(self.no_label, callback_data=self.NO_CALLBACK),
            ]
        ]
        if self.include_cancel:
            buttons.append([InlineKeyboardButton("Cancel", callback_data=self.CANCEL_CALLBACK)])
        
        return DialogResponse(
            text=self.prompt,
            keyboard=InlineKeyboardMarkup(buttons),
            edit_message=False,
        )

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle Yes/No/Cancel button press."""
        if callback_data == self.CANCEL_CALLBACK:
            return self.cancel()
        
        if callback_data == self.YES_CALLBACK:
            self._value = True
            self.state = DialogState.COMPLETE
            return DialogResponse(
                text=f"{self.yes_label}",
                keyboard=None,
                edit_message=False,
            )
        
        if callback_data == self.NO_CALLBACK:
            self._value = False
            self.state = DialogState.COMPLETE
            return DialogResponse(
                text=f"{self.no_label}",
                keyboard=None,
                edit_message=False,
            )
        
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

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Start the first dialog in the sequence."""
        if context is not None:
            self._context = context
        self.state = DialogState.ACTIVE
        self._current_index = 0
        
        if not self._dialogs:
            self.state = DialogState.COMPLETE
            return DialogResponse(text="Sequence complete.", keyboard=None, edit_message=False)
        
        # Pass context to first child
        name, dialog = self._dialogs[0]
        return dialog.start(self.context)

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to current child dialog."""
        current = self.current_dialog
        if current is None:
            return None
        
        response = current.handle_callback(callback_data)
        return self._handle_child_response(response)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to current child dialog."""
        current = self.current_dialog
        if current is None:
            return None
        
        response = current.handle_text_input(text)
        return self._handle_child_response(response)

    def _handle_child_response(self, response: Optional[DialogResponse]) -> Optional[DialogResponse]:
        """Check if child completed and advance if needed."""
        current = self.current_dialog
        if current is None:
            return response
        
        if current.is_complete:
            # Update context with child's value
            name = self._dialogs[self._current_index][0]
            self.context[name] = current.value
            
            # Check if child was cancelled
            if current.value is None:
                # Bubble up cancellation
                return self.cancel()
            
            # Advance to next dialog
            self._current_index += 1
            
            if self._current_index >= len(self._dialogs):
                # All dialogs complete
                self._value = self.values
                self.state = DialogState.COMPLETE
                return response
            
            # Start next dialog
            name, next_dialog = self._dialogs[self._current_index]
            next_response = next_dialog.start(self.context)
            
            # Return the completion response, then the next dialog's start
            # For simplicity, just return the next dialog's start
            return next_response
        
        return response

    def reset(self) -> None:
        """Reset sequence and all child dialogs."""
        super().reset()
        self._current_index = 0
        for _, dialog in self._dialogs:
            dialog.reset()


class BranchDialog(Dialog):
    """Composite dialog: Condition-based branching.
    
    Evaluates a condition function on start to select which branch to run.
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

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Evaluate condition and start selected branch."""
        if context is not None:
            self._context = context
        self.state = DialogState.ACTIVE
        
        # Evaluate condition to select branch
        branch_key = self.condition(self.context)
        
        if branch_key not in self.branches:
            logger = get_logger()
            logger.error("branch_key_not_found key=%s", branch_key)
            return self.cancel()
        
        self._active_key = branch_key
        self._active_branch = self.branches[branch_key]
        
        return self._active_branch.start(self.context)

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to active branch."""
        if self._active_branch is None:
            return None
        
        response = self._active_branch.handle_callback(callback_data)
        return self._handle_branch_response(response)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to active branch."""
        if self._active_branch is None:
            return None
        
        response = self._active_branch.handle_text_input(text)
        return self._handle_branch_response(response)

    def _handle_branch_response(self, response: Optional[DialogResponse]) -> Optional[DialogResponse]:
        """Check if branch completed."""
        if self._active_branch and self._active_branch.is_complete:
            self._value = self._active_branch.value
            self.state = DialogState.COMPLETE
        return response

    def reset(self) -> None:
        """Reset branch dialog."""
        super().reset()
        self._active_branch = None
        self._active_key = None
        for dialog in self.branches.values():
            dialog.reset()


class ChoiceBranchDialog(Dialog):
    """Composite dialog: User selects branch via keyboard.
    
    Shows a prompt with buttons, each button leads to a different dialog branch.
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

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Show branch selection keyboard."""
        if context is not None:
            self._context = context
        self.state = DialogState.ACTIVE
        self._choosing = True
        self._active_branch = None
        self._active_key = None
        
        return DialogResponse(
            text=self.prompt,
            keyboard=self._build_keyboard(),
            edit_message=False,
        )

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Handle branch selection or delegate to active branch."""
        if self._choosing:
            # User is selecting a branch
            if callback_data == self.CANCEL_CALLBACK:
                return self.cancel()
            
            if callback_data not in self.branches:
                return None
            
            # Start the selected branch
            self._active_key = callback_data
            label, dialog = self.branches[callback_data]
            self._active_branch = dialog
            self._choosing = False
            
            return self._active_branch.start(self.context)
        
        # Delegate to active branch
        if self._active_branch is None:
            return None
        
        response = self._active_branch.handle_callback(callback_data)
        return self._handle_branch_response(response)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to active branch if running."""
        if self._choosing:
            return None  # Not accepting text while choosing
        
        if self._active_branch is None:
            return None
        
        response = self._active_branch.handle_text_input(text)
        return self._handle_branch_response(response)

    def _handle_branch_response(self, response: Optional[DialogResponse]) -> Optional[DialogResponse]:
        """Check if branch completed."""
        if self._active_branch and self._active_branch.is_complete:
            self._value = self._active_branch.value
            self.state = DialogState.COMPLETE
        return response

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
    - value == exit_value, OR
    - exit_condition(value) returns True, OR
    - max_iterations reached
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

    def start(self, context: Optional[Dict[str, Any]] = None) -> DialogResponse:
        """Start the first iteration."""
        if context is not None:
            self._context = context
        self.state = DialogState.ACTIVE
        self._iterations = 0
        self._all_values = []
        
        self.dialog.reset()
        return self.dialog.start(self.context)

    def handle_callback(self, callback_data: str) -> Optional[DialogResponse]:
        """Delegate to inner dialog."""
        response = self.dialog.handle_callback(callback_data)
        return self._handle_iteration_response(response)

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Delegate to inner dialog."""
        response = self.dialog.handle_text_input(text)
        return self._handle_iteration_response(response)

    def _handle_iteration_response(self, response: Optional[DialogResponse]) -> Optional[DialogResponse]:
        """Check if iteration complete and decide whether to loop or exit."""
        if not self.dialog.is_complete:
            return response
        
        value = self.dialog.value
        self._iterations += 1
        self._all_values.append(value)
        
        # Check exit conditions
        should_exit = False
        
        if value is None:
            # Cancelled - exit loop
            should_exit = True
        elif self.exit_value is not None and value == self.exit_value:
            should_exit = True
        elif self.exit_condition is not None and self.exit_condition(value):
            should_exit = True
        elif self.max_iterations is not None and self._iterations >= self.max_iterations:
            should_exit = True
        
        if should_exit:
            self._value = value  # Last value that triggered exit
            self.state = DialogState.COMPLETE
            return response
        
        # Continue looping - reset and restart
        self.dialog.reset()
        return self.dialog.start(self.context)

    def reset(self) -> None:
        """Reset loop dialog."""
        super().reset()
        self._iterations = 0
        self._all_values = []
        self.dialog.reset()
