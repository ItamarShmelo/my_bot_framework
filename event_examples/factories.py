"""Factory functions for creating common event patterns.

These factories create ActivateOnConditionEvent instances configured for
common use cases, reducing boilerplate.

For class-based approaches, see TimeEvent and ThresholdEvent in this package.
"""

import os
import time
from typing import Callable, List, Union

from ..event import (
    ActivateOnConditionEvent,
    EditableAttribute,
    FunctionMessageBuilder,
    Condition,
    MessageBuilder,
)
from ..telegram_utilities import TelegramMessage


def create_threshold_event(
    event_name: str,
    value_getter: Callable[[], float],
    threshold: float,
    message_builder: Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
    above: bool = True,
    poll_seconds: float = 10.0,
    cooldown_seconds: float = 60.0,
    fire_when_edited: bool = False,
) -> ActivateOnConditionEvent:
    """Create an event that fires when a value crosses a threshold.
    
    Args:
        event_name: Unique identifier for the event.
        value_getter: Callable that returns the current value to check.
        threshold: The threshold value to compare against.
        message_builder: Callable returning message content.
        above: If True, fire when value > threshold. If False, when value < threshold.
        poll_seconds: How often to check the condition.
        cooldown_seconds: Minimum time between fires to prevent spam.
        fire_when_edited: If True, fire immediately when edited (even if condition is False).
        
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
    class ThresholdCondition(Condition):
        def __init__(self) -> None:
            threshold_attr = EditableAttribute(
                name="threshold",
                field_type=(int, float),
                initial_value=threshold,
                parse=float,
            )
            self.editable_attributes = [threshold_attr]
            self._edited = False
            self._state = {
                "last_fire_time": None,
            }
        
        def check(self) -> bool:
            """Return True when value crosses threshold (with cooldown)."""
            now = time.time()
            
            # Check cooldown
            if self._state["last_fire_time"] is not None:
                elapsed = now - self._state["last_fire_time"]
                if elapsed < cooldown_seconds:
                    return False
            
            value = value_getter()
            current_threshold = self.get("threshold")
            
            if above:
                triggered = value > current_threshold
            else:
                triggered = value < current_threshold
            
            if triggered:
                self._state["last_fire_time"] = now
            
            return triggered
    
    condition = ThresholdCondition()
    builder = FunctionMessageBuilder(
        builder=message_builder,
    )
    return ActivateOnConditionEvent(
        event_name=event_name,
        condition=condition,
        message_builder=builder,
        poll_seconds=poll_seconds,
        fire_when_edited=fire_when_edited,
    )


def _validate_file_exists(path: str) -> tuple[bool, str]:
    """Validate that a file path exists."""
    if os.path.isfile(path):
        return True, ""
    return False, f"File does not exist: {path}"


def create_file_change_event(
    event_name: str,
    file_path: str,
    message_builder: Callable[[str], Union[None, TelegramMessage, str, List[TelegramMessage]]],
    poll_seconds: float = 30.0,
    fire_when_edited: bool = False,
) -> ActivateOnConditionEvent:
    """Create an event that fires when a file is modified.
    
    Monitors a file's modification time and fires when it changes.
    The file path is editable at runtime.
    
    Args:
        event_name: Unique identifier for the event.
        file_path: Path to the file to monitor. Editable at runtime.
        message_builder: Callable that receives current file path and returns message content.
        poll_seconds: How often to check for changes.
        fire_when_edited: If True, fire immediately when edited (even if condition is False).
    Returns:
        An ActivateOnConditionEvent configured for file monitoring.
        The event has an editable `file_path` field.
        
    Example:
        >>> event = create_file_change_event(
        ...     event_name="config_changed",
        ...     file_path="/etc/myapp/config.yaml",
        ...     message_builder=lambda path: f"Config modified: {path}",
        ... )
        >>> # Edit file path at runtime:
        >>> event.edit("condition.file_path", "/etc/myapp/other.yaml")
    """
    class FileChangeCondition(Condition):
        def __init__(self) -> None:
            file_path_attr = EditableAttribute(
                name="file_path",
                field_type=str,
                initial_value=file_path,
                parse=str,
                validator=_validate_file_exists,
            )
            self.editable_attributes = [file_path_attr]
            self._edited = False
            self._state = {
                "last_mtime": None,
                "last_path": file_path,  # Track path changes
            }
        
        def check(self) -> bool:
            """Return True when file modification time changes."""
            current_path = self.get("file_path")
            
            # If path changed, reset state
            if current_path != self._state["last_path"]:
                self._state["last_path"] = current_path
                self._state["last_mtime"] = None
            
            try:
                current_mtime = os.path.getmtime(current_path)
            except OSError:
                # File doesn't exist or not accessible
                return False
            
            if self._state["last_mtime"] is None:
                # First check - record initial state, don't fire
                self._state["last_mtime"] = current_mtime
                return False
            
            if current_mtime != self._state["last_mtime"]:
                self._state["last_mtime"] = current_mtime
                return True
            
            return False
    
    class FileChangeMessageBuilder(MessageBuilder):
        def __init__(self, condition: FileChangeCondition) -> None:
            self.editable_attributes = []
            self._edited = False
            self._condition = condition
        
        def build(self) -> Union[None, TelegramMessage, str, List[TelegramMessage]]:
            current_path = self._condition.get("file_path")
            return message_builder(current_path)
    
    condition = FileChangeCondition()
    builder = FileChangeMessageBuilder(condition)
    return ActivateOnConditionEvent(
        event_name=event_name,
        condition=condition,
        message_builder=builder,
        poll_seconds=poll_seconds,
        fire_when_edited=fire_when_edited,
    )
