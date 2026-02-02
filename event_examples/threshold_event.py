"""ThresholdEvent - An event that fires when a value crosses a threshold.

This is an example of extending ActivateOnConditionEvent for a common pattern.
"""

import time
from typing import Callable, List, Union

from ..event import (
    ActivateOnConditionEvent,
    EditableAttribute,
    Condition,
    FunctionMessageBuilder,
)
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
        message_builder: Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
        above: bool = True,
        poll_seconds: float = 10.0,
        cooldown_seconds: float = 60.0,
        fire_when_edited: bool = False,
    ) -> None:
        """Initialize the threshold event.
        
        Args:
            event_name: Unique identifier for the event.
            value_getter: Callable that returns the current value to check.
            threshold: The threshold value to compare against. Editable at runtime.
            message_builder: Callable returning message content.
            above: If True, fire when value > threshold. If False, when value < threshold.
            poll_seconds: How often to check the condition.
            cooldown_seconds: Minimum time between fires to prevent spam.
            fire_when_edited: If True, fire immediately when edited (even if condition is False).
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
        super().__init__(
            event_name=event_name,
            condition=condition,
            message_builder=builder,
            poll_seconds=poll_seconds,
            fire_when_edited=fire_when_edited,
        )
    
    @property
    def threshold(self) -> float:
        """Get the current threshold value."""
        return self.get("condition.threshold")
    
    @threshold.setter
    def threshold(self, value: float) -> None:
        """Set the threshold value."""
        self.edit("condition.threshold", value)
