"""Generic utilities for the bot framework."""

import html
from typing import List


def divide_message_to_chunks(message: str, chunk_size: int) -> List[str]:
    """Split a message into fixed-size chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not message:
        return []
    return [message[index : index + chunk_size] for index in range(0, len(message), chunk_size)]


def format_numbered_list(items: list[str], start: int = 1) -> str:
    """Format a list of items as a numbered list for Telegram messages.

    Each item is HTML-escaped to prevent injection when using HTML parse mode.

    Args:
        items: List of strings to format as numbered items.
        start: Starting number for the list (default 1).

    Returns:
        Formatted string with numbered items, or empty string if items is empty.

    Example:
        >>> format_numbered_list(["Apple", "Banana"])
        '1. Apple\\n2. Banana'
        >>> format_numbered_list(["First", "Second"], start=5)
        '5. First\\n6. Second'
    """
    if not items:
        return ""
    return "\n".join(
        f"{start + index}. {html.escape(item)}"
        for index, item in enumerate(items)
    )


def format_bullet_list(items: list[str], bullet: str = "•") -> str:
    """Format a list of items as a bullet list for Telegram messages.

    Each item is HTML-escaped to prevent injection when using HTML parse mode.

    Args:
        items: List of strings to format as bullet items.
        bullet: Character to use as bullet point (default "•").

    Returns:
        Formatted string with bullet items, or empty string if items is empty.

    Example:
        >>> format_bullet_list(["Apple", "Banana"])
        '• Apple\\n• Banana'
        >>> format_bullet_list(["One", "Two"], bullet="-")
        '- One\\n- Two'
    """
    if not items:
        return ""
    return "\n".join(
        f"{bullet} {html.escape(item)}"
        for item in items
    )


def format_key_value_pairs(pairs: list[tuple[str, str]], separator: str = ": ") -> str:
    """Format key-value pairs as a list for Telegram messages.

    Both keys and values are HTML-escaped to prevent injection when using
    HTML parse mode.

    Args:
        pairs: List of (key, value) tuples to format.
        separator: String to use between key and value (default ": ").

    Returns:
        Formatted string with key-value pairs, or empty string if pairs is empty.

    Example:
        >>> format_key_value_pairs([("Name", "John"), ("Age", "30")])
        'Name: John\\nAge: 30'
        >>> format_key_value_pairs([("A", "1")], separator=" = ")
        'A = 1'
    """
    if not pairs:
        return ""
    return "\n".join(
        f"{html.escape(key)}{separator}{html.escape(value)}"
        for key, value in pairs
    )
