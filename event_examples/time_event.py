"""TimeEvent - A time-based event that fires at regular intervals.

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


MINIMAL_INTERVAL_HOURS = 5.0 / 60.0  # 5 minutes


class TimeEvent(ActivateOnConditionEvent):
    """Emit messages at regular time intervals.
    
    A subclass of ActivateOnConditionEvent that uses a time-based condition.
    The interval is editable at runtime.
    
    Example:
        >>> event = TimeEvent(
        ...     event_name="hourly_status",
        ...     interval_hours=1.0,
        ...     message_builder=lambda: "Hourly ping!",
        ...     fire_on_first_check=True,
        ... )
        >>> app.register_event(event)
        >>> 
        >>> # Edit interval at runtime:
        >>> event.interval_hours = 0.5  # Change to 30 minutes
    """
    
    def __init__(
        self,
        event_name: str,
        interval_hours: float,
        message_builder: Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
        fire_on_first_check: bool = False,
    ) -> None:
        """Initialize the time-based event.
        
        Args:
            event_name: Unique identifier for the event.
            interval_hours: Hours between emissions (minimum 5 minutes). Editable at runtime.
            message_builder: Callable returning message content.
            fire_on_first_check: If True, fire immediately on first check.
        """
        assert interval_hours >= MINIMAL_INTERVAL_HOURS, (
            f"interval_hours must be at least {MINIMAL_INTERVAL_HOURS * 60:.0f} minutes"
        )

        class TimeCondition(Condition):
            def __init__(self) -> None:
                interval_attr = EditableAttribute(
                    name="interval_hours",
                    field_type=(int, float),
                    initial_value=interval_hours,
                    parse=float,
                    validator=lambda v: (
                        v >= MINIMAL_INTERVAL_HOURS,
                        f"interval_hours must be at least {MINIMAL_INTERVAL_HOURS * 60:.0f} minutes"
                    ),
                )
                self.editable_attributes = [interval_attr]
                self._edited = False
                self._state = {
                    "last_fire_time": None,
                    "first_check": True,
                }
                self._fire_on_first_check = fire_on_first_check
            
            def check(self) -> bool:
                """Return True when the interval has elapsed."""
                now = time.time()
                
                # Get current interval from editable attribute
                current_interval_seconds = self.get("interval_hours") * 3600.0
                
                # Handle first check
                if self._state["first_check"]:
                    self._state["first_check"] = False
                    if self._fire_on_first_check:
                        self._state["last_fire_time"] = now
                        return True
                    else:
                        self._state["last_fire_time"] = now
                        return False
                
                # Check if interval has elapsed
                if self._state["last_fire_time"] is None:
                    self._state["last_fire_time"] = now
                    return False
                
                elapsed = now - self._state["last_fire_time"]
                if elapsed >= current_interval_seconds:
                    self._state["last_fire_time"] = now
                    return True
                
                return False
            
        # Calculate poll interval (poll at least twice per interval, max 60s)
        initial_interval_seconds = interval_hours * 3600.0
        poll_seconds = min(initial_interval_seconds / 2, 60.0)

        condition = TimeCondition()
        builder = FunctionMessageBuilder(builder=message_builder)
        super().__init__(
            event_name=event_name,
            condition=condition,
            message_builder=builder,
            poll_seconds=poll_seconds,
        )
    
    @property
    def interval_hours(self) -> float:
        """Get the current interval in hours."""
        return self.get("condition.interval_hours")
    
    @interval_hours.setter
    def interval_hours(self, value: float) -> None:
        """Set the interval in hours."""
        self.edit("condition.interval_hours", value)
