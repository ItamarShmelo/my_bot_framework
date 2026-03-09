"""Factory functions for creating dialogs with a specified keyboard type."""

from __future__ import annotations

from typing import Any, Callable

from .base import BranchesType, Dialog, KeyboardType
from .choice import ChoiceDialog
from .confirm import ConfirmDialog
from .paginated import PaginatedChoiceDialog
from .branch import ChoiceBranchDialog
from .input import UserInputDialog


def create_choice_dialog(
    prompt: str,
    choices: list[tuple[str, str]] | Callable[[dict[str, Any]], list[tuple[str, str]]],
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    include_cancel: bool = True,
) -> Dialog[str]:
    """Create a choice dialog with specified keyboard type.

    Args:
        prompt: The question text to display.
        choices: List of (label, callback_data) tuples, or callable(context)
            returning same.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        include_cancel: If True, add a Cancel button.

    Returns:
        A ChoiceDialog instance configured with the given keyboard type.
    """
    return ChoiceDialog(
        prompt,
        choices,
        include_cancel=include_cancel,
        keyboard_type=keyboard_type,
    )


def create_confirm_dialog(
    prompt: str,
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    yes_label: str = "Yes",
    no_label: str = "No",
    include_cancel: bool = False,
) -> Dialog[bool]:
    """Create a confirmation dialog with specified keyboard type.

    Args:
        prompt: The question text to display.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        yes_label: Label for the Yes button.
        no_label: Label for the No button.
        include_cancel: If True, add a Cancel button.

    Returns:
        A ConfirmDialog instance configured with the given keyboard type.
    """
    return ConfirmDialog(
        prompt,
        yes_label=yes_label,
        no_label=no_label,
        include_cancel=include_cancel,
        keyboard_type=keyboard_type,
    )


def create_paginated_choice_dialog(
    prompt: str,
    items: list[tuple[str, str]] | Callable[[dict[str, Any]], list[tuple[str, str]]],
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    page_size: int = 5,
    include_cancel: bool = True,
) -> Dialog[str]:
    """Create a paginated choice dialog with specified keyboard type.

    Args:
        prompt: The question text to display.
        items: List of (label, callback_data) tuples, or callable(context)
            returning same.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        page_size: Number of items to show per page (default 5).
        include_cancel: If True, add a Cancel button.

    Returns:
        A PaginatedChoiceDialog instance configured with the given keyboard type.
    """
    return PaginatedChoiceDialog(
        prompt,
        items,
        page_size=page_size,
        keyboard_type=keyboard_type,
        include_cancel=include_cancel,
    )


def create_choice_branch_dialog(
    prompt: str,
    branches: BranchesType,
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    include_cancel: bool = True,
) -> Dialog[dict[str, Any] | None]:
    """Create a choice-branch dialog with specified keyboard type.

    Args:
        prompt: The question text to display.
        branches: Dict mapping keys to (label, dialog) tuples,
            or callable(context) returning same.
        keyboard_type: Type of keyboard to use (INLINE or REPLY).
        include_cancel: If True, add a Cancel button.

    Returns:
        A ChoiceBranchDialog instance configured with the given keyboard type.
    """
    return ChoiceBranchDialog(
        prompt,
        branches,
        include_cancel=include_cancel,
        keyboard_type=keyboard_type,
    )


def create_user_input_dialog(
    prompt: str | Callable[[], str],
    keyboard_type: KeyboardType = KeyboardType.INLINE,
    validator: Callable[[str], tuple[bool, str]] | None = None,
    include_cancel: bool = True,
) -> UserInputDialog:
    """Create a user input dialog with specified keyboard type.

    Args:
        prompt: The question text to display or a callable that returns it.
        keyboard_type: Type of keyboard to use for Cancel button
            (INLINE or REPLY). Defaults to INLINE.
        validator: Optional callable(text) -> (is_valid, error_message).
        include_cancel: If True, add a Cancel button.

    Returns:
        A UserInputDialog instance configured with the given keyboard type.
    """
    return UserInputDialog(
        prompt=prompt,
        validator=validator,
        include_cancel=include_cancel,
        keyboard_type=keyboard_type,
    )
