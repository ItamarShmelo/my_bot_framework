"""Dialog system for interactive multi-step Telegram conversations.

This package implements the Composite pattern for building complex dialogs
from simple atomic components (leaf dialogs) and composites.

Leaf dialogs (one question each):
- ChoiceDialog: User selects from keyboard options
- PaginatedChoiceDialog: User selects from paginated keyboard options
- UserInputDialog: User enters text
- ConfirmDialog: Yes/No prompt
- EditEventDialog: Edit an event's editable attributes via keyboard

Composite dialogs:
- SequenceDialog: Run dialogs in order
- BranchDialog: Condition-based branching
- ChoiceBranchDialog: User selects branch via keyboard
- LoopDialog: Repeat until exit condition
"""

from .base import (
    BUTTON_SELECTION_REMINDER,
    DIALOG_DEBUG,
    DONE_CALLBACK,
    BranchesType,
    Dialog,
    DialogResult,
    DialogState,
    KeyboardType,
    is_cancelled,
    set_dialog_debug,
)
from .choice import ChoiceDialog
from .confirm import ConfirmDialog
from .paginated import PaginatedChoiceDialog
from .branch import ChoiceBranchDialog
from .input import UserInputDialog
from .composite import (
    BranchDialog,
    DialogHandler,
    LoopDialog,
    SequenceDialog,
)
from .edit import EditEventDialog
from .factories import (
    create_choice_branch_dialog,
    create_choice_dialog,
    create_confirm_dialog,
    create_paginated_choice_dialog,
    create_user_input_dialog,
)

__all__ = [
    # Base
    "Dialog",
    "DialogState",
    "DialogResult",
    "DialogHandler",
    "KeyboardType",
    "BranchesType",
    "BUTTON_SELECTION_REMINDER",
    "DONE_CALLBACK",
    # Dialog classes
    "ChoiceDialog",
    "ConfirmDialog",
    "PaginatedChoiceDialog",
    "ChoiceBranchDialog",
    # Other dialogs
    "UserInputDialog",
    "SequenceDialog",
    "BranchDialog",
    "LoopDialog",
    "EditEventDialog",
    # Factory functions
    "create_choice_dialog",
    "create_confirm_dialog",
    "create_paginated_choice_dialog",
    "create_choice_branch_dialog",
    "create_user_input_dialog",
    # Sentinels and debug
    "is_cancelled",
    "DIALOG_DEBUG",
    "set_dialog_debug",
]
