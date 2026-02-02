"""Factory functions for creating common event patterns.

These factories create ActivateOnConditionEvent instances configured for
common use cases, reducing boilerplate.

For class-based approaches, see TimeEvent and ThresholdEvent in this package.
"""

import os
import time
from typing import Any, Callable, List, Optional, Union

from ..event import ActivateOnConditionEvent, EditableField
from ..telegram_utilities import TelegramMessage


def create_threshold_event(
    event_name: str,
    value_getter: Callable[[], float],
    threshold: float,
    message_builder: Callable[..., Union[None, TelegramMessage, str, List[TelegramMessage]]],
    above: bool = True,
    poll_seconds: float = 10.0,
    message_builder_args: tuple[Any, ...] = (),
    message_builder_kwargs: Optional[dict[str, Any]] = None,
    cooldown_seconds: float = 60.0,
) -> ActivateOnConditionEvent:
    """Create an event that fires when a value crosses a threshold.
    
    Args:
        event_name: Unique identifier for the event.
        value_getter: Callable that returns the current value to check.
        threshold: The threshold value to compare against.
        message_builder: Callable returning message content.
        above: If True, fire when value > threshold. If False, when value < threshold.
        poll_seconds: How often to check the condition.
        message_builder_args: Positional args for message_builder.
        message_builder_kwargs: Keyword args for message_builder.
        cooldown_seconds: Minimum time between fires to prevent spam.
        
    Returns:
        An ActivateOnConditionEvent configured for threshold monitoring.
        
    Example:
        >>> def get_cpu_usage():
        ...     return psutil.cpu_percent()
        >>> 
        >>> event = create_threshold_event(
        ...     event_name="high_cpu_alert",
        ...     value_getter=get_cpu_usage,
        ...     threshold=90.0,
        ...     message_builder=lambda: "CPU usage is high!",
        ...     above=True,
        ...     cooldown_seconds=300.0,  # 5 minute cooldown
        ... )
    """
    state = {
        "last_fire_time": None,
    }
    
    def threshold_condition() -> bool:
        """Return True when value crosses threshold (with cooldown)."""
        now = time.time()
        
        # Check cooldown
        if state["last_fire_time"] is not None:
            elapsed = now - state["last_fire_time"]
            if elapsed < cooldown_seconds:
                return False
        
        value = value_getter()
        
        if above:
            triggered = value > threshold
        else:
            triggered = value < threshold
        
        if triggered:
            state["last_fire_time"] = now
        
        return triggered
    
    # Create editable threshold field
    threshold_field = EditableField(
        name="threshold",
        field_type=(int, float),
        initial_value=threshold,
        parse=float,
    )
    
    return ActivateOnConditionEvent(
        event_name=event_name,
        condition_func=threshold_condition,
        message_builder=message_builder,
        message_builder_args=message_builder_args,
        message_builder_kwargs=message_builder_kwargs,
        editable_fields=[threshold_field],
        poll_seconds=poll_seconds,
    )


def _validate_file_exists(path: str) -> tuple[bool, str]:
    """Validate that a file path exists."""
    if os.path.isfile(path):
        return True, ""
    return False, f"File does not exist: {path}"


def create_file_change_event(
    event_name: str,
    file_path: str,
    message_builder: Callable[..., Union[None, TelegramMessage, str, List[TelegramMessage]]],
    poll_seconds: float = 30.0,
    message_builder_args: tuple[Any, ...] = (),
    message_builder_kwargs: Optional[dict[str, Any]] = None,
) -> ActivateOnConditionEvent:
    """Create an event that fires when a file is modified.
    
    Monitors a file's modification time and fires when it changes.
    The file path is editable at runtime.
    
    Args:
        event_name: Unique identifier for the event.
        file_path: Path to the file to monitor. Editable at runtime.
        message_builder: Callable returning message content.
        poll_seconds: How often to check for changes.
        message_builder_args: Positional args for message_builder.
        message_builder_kwargs: Keyword args for message_builder.
        
    Returns:
        An ActivateOnConditionEvent configured for file monitoring.
        The event has an editable `file_path` field.
        
    Example:
        >>> event = create_file_change_event(
        ...     event_name="config_changed",
        ...     file_path="/etc/myapp/config.yaml",
        ...     message_builder=lambda: "Config file was modified!",
        ... )
        >>> # Edit file path at runtime:
        >>> event.editable_fields[0].value = "/etc/myapp/other.yaml"
    """
    # Create editable file path field with existence validation
    file_path_field = EditableField(
        name="file_path",
        field_type=str,
        initial_value=file_path,
        parse=str,
        validator=_validate_file_exists,
    )
    
    state = {
        "last_mtime": None,
        "last_path": file_path,  # Track path changes
    }
    
    def file_changed_condition() -> bool:
        """Return True when file modification time changes."""
        current_path = file_path_field.value
        
        # If path changed, reset state
        if current_path != state["last_path"]:
            state["last_path"] = current_path
            state["last_mtime"] = None
        
        try:
            current_mtime = os.path.getmtime(current_path)
        except OSError:
            # File doesn't exist or not accessible
            return False
        
        if state["last_mtime"] is None:
            # First check - record initial state, don't fire
            state["last_mtime"] = current_mtime
            return False
        
        if current_mtime != state["last_mtime"]:
            state["last_mtime"] = current_mtime
            return True
        
        return False
    
    return ActivateOnConditionEvent(
        event_name=event_name,
        condition_func=file_changed_condition,
        message_builder=message_builder,
        message_builder_args=message_builder_args,
        message_builder_kwargs=message_builder_kwargs,
        editable_fields=[file_path_field],
        poll_seconds=poll_seconds,
    )
