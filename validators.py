"""Reusable validation functions for UserInputDialog.

This module provides a set of common validators that can be used with
UserInputDialog to validate user input. All validators follow the pattern:
    validator(value: str) -> tuple[bool, str]
where the tuple contains (is_valid, error_message).

Example:
    from my_bot_framework import UserInputDialog, validate_positive_float

    dialog = UserInputDialog(
        prompt="Enter price:",
        validator=validate_positive_float,
    )
"""

import re
from datetime import datetime
from typing import Callable, Tuple


# Type alias for validator functions
Validator = Callable[[str], Tuple[bool, str]]


def validate_positive_float(value: str) -> Tuple[bool, str]:
    """Validate that input is a positive decimal number.

    Accepts both integers and decimals (e.g., "5", "3.14", "0.5").

    Args:
        value: The input string to validate.

    Returns:
        Tuple of (is_valid, error_message). Error message is empty on success.
    """
    try:
        num = float(value)
        if num <= 0:
            return False, "Value must be positive."
        return True, ""
    except ValueError:
        return False, "Invalid number. Please enter a valid decimal number."


def validate_positive_int(value: str) -> Tuple[bool, str]:
    """Validate that input is a positive integer.

    Args:
        value: The input string to validate.

    Returns:
        Tuple of (is_valid, error_message). Error message is empty on success.
    """
    try:
        num = int(value)
        if num <= 0:
            return False, "Value must be a positive integer."
        return True, ""
    except ValueError:
        return False, "Invalid integer. Please enter a whole number."


def validate_non_empty(value: str) -> Tuple[bool, str]:
    """Validate that input is non-empty after stripping whitespace.

    Args:
        value: The input string to validate.

    Returns:
        Tuple of (is_valid, error_message). Error message is empty on success.
    """
    if not value.strip():
        return False, "Value cannot be empty."
    return True, ""


def validate_int_range(min_val: int, max_val: int) -> Validator:
    """Create a validator for integers within a specific range.

    Factory function that returns a validator checking if the input is an
    integer between min_val and max_val (inclusive).

    Args:
        min_val: Minimum allowed value (inclusive).
        max_val: Maximum allowed value (inclusive).

    Returns:
        A validator function that checks if input is an integer in the range.

    Example:
        validator = validate_int_range(1, 100)
        dialog = UserInputDialog(prompt="Enter age:", validator=validator)
    """
    def validator(value: str) -> Tuple[bool, str]:
        """Validate integer is within the specified range."""
        try:
            num = int(value)
            if num < min_val or num > max_val:
                return False, f"Value must be between {min_val} and {max_val}."
            return True, ""
        except ValueError:
            return False, "Invalid integer. Please enter a whole number."
    return validator


def validate_float_range(min_val: float, max_val: float) -> Validator:
    """Create a validator for floats within a specific range.

    Factory function that returns a validator checking if the input is a
    float between min_val and max_val (inclusive).

    Args:
        min_val: Minimum allowed value (inclusive).
        max_val: Maximum allowed value (inclusive).

    Returns:
        A validator function that checks if input is a float in the range.

    Example:
        validator = validate_float_range(0.0, 1.0)
        dialog = UserInputDialog(prompt="Enter probability:", validator=validator)
    """
    def validator(value: str) -> Tuple[bool, str]:
        """Validate float is within the specified range."""
        try:
            num = float(value)
            if num < min_val or num > max_val:
                return False, f"Value must be between {min_val} and {max_val}."
            return True, ""
        except ValueError:
            return False, "Invalid number. Please enter a valid decimal number."
    return validator


def validate_date_format(fmt: str = "%m/%Y", description: str = "MM/YYYY") -> Validator:
    """Create a validator for date strings matching a specific format.

    Factory function that returns a validator checking if the input can be
    parsed using datetime.strptime with the given format string.

    Args:
        fmt: The datetime format string (default: "%m/%Y").
        description: Human-readable description of the format for error messages
            (default: "MM/YYYY").

    Returns:
        A validator function that checks if input matches the date format.

    Example:
        validator = validate_date_format("%Y-%m-%d", "YYYY-MM-DD")
        dialog = UserInputDialog(prompt="Enter date:", validator=validator)
    """
    def validator(value: str) -> Tuple[bool, str]:
        """Validate string matches the specified date format."""
        try:
            datetime.strptime(value.strip(), fmt)
            return True, ""
        except ValueError:
            return False, f"Invalid date format. Please use {description}."
    return validator


def validate_regex(pattern: str, error_msg: str) -> Validator:
    """Create a validator that matches against a regex pattern.

    Factory function that returns a validator checking if the input matches
    the given regular expression pattern (full match).

    Args:
        pattern: The regular expression pattern to match against.
        error_msg: The error message to display if validation fails.

    Returns:
        A validator function that checks if input matches the pattern.

    Example:
        validator = validate_regex(r"^[a-z_][a-z0-9_]*$", "Invalid identifier format.")
        dialog = UserInputDialog(prompt="Enter name:", validator=validator)
    """
    compiled = re.compile(pattern)

    def validator(value: str) -> Tuple[bool, str]:
        """Validate string matches the specified regex pattern."""
        if compiled.fullmatch(value):
            return True, ""
        return False, error_msg
    return validator
