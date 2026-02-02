"""ThresholdEvent - An event that fires when a value crosses a threshold.

This is an example of extending ActivateOnConditionEvent for a common pattern.
"""

import time
from typing import Any, Callable, List, Optional, Union

from ..event import ActivateOnConditionEvent, EditableField
from ..telegram_utilities import TelegramMessage


class ThresholdEvent(ActivateOnConditionEvent):
    """Emit messages when a monitored value crosses a threshold.
    
    A subclass of ActivateOnConditionEvent that monitors a value and fires
    when it goes above (or below) a threshold. Includes cooldown to prevent spam.
    The threshold is editable at runtime.
    
    Example:
        >>> def get_cpu_usage():
        ...     return psutil.cpu_percent()
        >>> 
        >>> event = ThresholdEvent(
        ...     event_name="high_cpu_alert",
        ...     value_getter=get_cpu_usage,
        ...     threshold=90.0,
        ...     message_builder=lambda: f"CPU usage is high: {get_cpu_usage()}%",
        ...     above=True,
        ...     cooldown_seconds=300.0,  # 5 minute cooldown
        ... )
        >>> app.register_event(event)
        >>> 
        >>> # Edit threshold at runtime:
        >>> event.threshold = 80.0
    """
    
    def __init__(
        self,
        event_name: str,
        value_getter: Callable[[], float],
        threshold: float,
        message_builder: Callable[..., Union[None, TelegramMessage, str, List[TelegramMessage]]],
        above: bool = True,
        poll_seconds: float = 10.0,
        message_builder_args: tuple[Any, ...] = (),
        message_builder_kwargs: Optional[dict[str, Any]] = None,
        cooldown_seconds: float = 60.0,
    ) -> None:
        """Initialize the threshold event.
        
        Args:
            event_name: Unique identifier for the event.
            value_getter: Callable that returns the current value to check.
            threshold: The threshold value to compare against. Editable at runtime.
            message_builder: Callable returning message content.
            above: If True, fire when value > threshold. If False, when value < threshold.
            poll_seconds: How often to check the condition.
            message_builder_args: Positional args for message_builder.
            message_builder_kwargs: Keyword args for message_builder.
            cooldown_seconds: Minimum time between fires to prevent spam.
        """
        self._value_getter = value_getter
        self._above = above
        self._cooldown_seconds = cooldown_seconds
        
        # Create editable threshold field
        self._threshold_field = EditableField(
            name="threshold",
            field_type=(int, float),
            initial_value=threshold,
            parse=float,
        )
        
        # State for cooldown
        self._threshold_state = {
            "last_fire_time": None,
        }
        
        super().__init__(
            event_name=event_name,
            condition_func=self._threshold_condition,
            message_builder=message_builder,
            message_builder_args=message_builder_args,
            message_builder_kwargs=message_builder_kwargs,
            editable_fields=[self._threshold_field],
            poll_seconds=poll_seconds,
        )
    
    @property
    def threshold(self) -> float:
        """Get the current threshold value."""
        return self._threshold_field.value
    
    @threshold.setter
    def threshold(self, value: float) -> None:
        """Set the threshold value."""
        self._threshold_field.value = value
        self.edited = True  # Trigger immediate re-check
    
    def _threshold_condition(self) -> bool:
        """Return True when value crosses threshold (with cooldown)."""
        now = time.time()
        
        # Check cooldown
        if self._threshold_state["last_fire_time"] is not None:
            elapsed = now - self._threshold_state["last_fire_time"]
            if elapsed < self._cooldown_seconds:
                return False
        
        value = self._value_getter()
        current_threshold = self._threshold_field.value
        
        if self._above:
            triggered = value > current_threshold
        else:
            triggered = value < current_threshold
        
        if triggered:
            self._threshold_state["last_fire_time"] = now
        
        return triggered
