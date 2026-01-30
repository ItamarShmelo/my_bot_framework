"""Generic utilities for the bot framework."""

import html
import re
from typing import List


class CallUpdatesInternalState:
    """Mixin for callable classes that update internal state from kwargs.
    
    The base __call__ validates that kwargs correspond to existing attributes,
    then applies them to internal state.
    
    Usage:
        class MyBuilder(CallUpdatesInternalState):
            def __init__(self, limit_min, limit_max, log_scale):
                self.limit_min = limit_min
                self.limit_max = limit_max
                self.log_scale = log_scale
            
            async def __call__(self, target, **kwargs):
                super().__call__(**kwargs)
                # Now self.limit_min, etc. are updated if passed
                ...
    """
    
    def __call__(self, **kwargs) -> None:
        """Update internal state from kwargs.
        
        Validates that all kwargs correspond to existing attributes on self,
        then applies them. Subclasses should call super().__call__(**kwargs).
        
        Raises:
            AssertionError: If any kwarg is not an existing attribute.
        """
        for key, value in kwargs.items():
            assert hasattr(self, key), (
                f"Unknown kwarg '{key}' - attribute does not exist on {type(self).__name__}"
            )
            setattr(self, key, value)


def divide_message_to_chunks(message: str, chunk_size: int) -> List[str]:
    """Split a message into fixed-size chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not message:
        return []
    return [message[index : index + chunk_size] for index in range(0, len(message), chunk_size)]


def format_message_html(pairs: List[tuple[str, object, str | None]]) -> str:
    """Format key/value pairs into an HTML <pre> block."""
    assert pairs, "pairs must not be empty"

    label_width = max(len(label) for label, _, _ in pairs)
    lines = []
    for label, value, value_format in pairs:
        padded_label = label.ljust(label_width)
        if value_format:
            formatted_value = format(value, value_format)
        else:
            formatted_value = _format_value_with_scientific(value)
        if "\n" in formatted_value:
            indent = " " * (label_width + 3)
            value_lines = formatted_value.split("\n")
            formatted_value = value_lines[0] + "\n" + "\n".join(
                f"{indent}{line}" for line in value_lines[1:]
            )
        lines.append(
            f"<b>{html.escape(padded_label)}</b> : {html.escape(formatted_value)}"
        )
    return f"<pre>{'\n'.join(lines)}</pre>"


def _format_value_with_scientific(value: object) -> str:
    """Render tuple/list strings with scientific notation alignment."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("(") and text.endswith(")"):
            return _format_container(text, "(", ")")
        if text.startswith("[") and text.endswith("]"):
            return _format_container(text, "[", "]")
        return text
    return str(value)


def _format_container(text: str, open_char: str, close_char: str) -> str:
    """Format tuple/list content into vertical aligned entries."""
    inner = text[len(open_char) : -len(close_char)]
    parts = [part.strip() for part in inner.split(",")]
    formatted_parts = []
    for part in parts:
        if not part:
            continue
        if re.match(r"^[+-]?\d+$", part):
            formatted_parts.append(part)
        elif re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$", part):
            formatted_parts.append(format(float(part), ".2e"))
        else:
            formatted_parts.append(part)
    if not formatted_parts:
        return f"{open_char}{close_char}"

    indent = "  "
    lines = []
    for index, value in enumerate(formatted_parts):
        suffix = "," if index < len(formatted_parts) - 1 else ""
        lines.append(f"{indent}{value}{suffix}")
    return f"{open_char}\n" + "\n".join(lines) + f"\n{close_char}"
