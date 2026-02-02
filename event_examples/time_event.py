"""TimeEvent - A time-based event that fires at regular intervals.

This is an example of extending ActivateOnConditionEvent for a common pattern.
"""

import time
from typing import Any, Callable, List, Optional, Union

from ..event import ActivateOnConditionEvent, EditableField
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
        message_builder: Callable[..., Union[None, TelegramMessage, str, List[TelegramMessage]]],
        message_builder_args: tuple[Any, ...] = (),
        message_builder_kwargs: Optional[dict[str, Any]] = None,
        fire_on_first_check: bool = False,
    ) -> None:
        """Initialize the time-based event.
        
        Args:
            event_name: Unique identifier for the event.
            interval_hours: Hours between emissions (minimum 5 minutes). Editable at runtime.
            message_builder: Callable returning message content.
            message_builder_args: Positional args for message_builder.
            message_builder_kwargs: Keyword args for message_builder.
            fire_on_first_check: If True, fire immediately on first check.
        """
        assert interval_hours >= MINIMAL_INTERVAL_HOURS, (
            f"interval_hours must be at least {MINIMAL_INTERVAL_HOURS * 60:.0f} minutes"
        )
        
        # Create editable interval field
        self._interval_field = EditableField(
            name="interval_hours",
            field_type=(int, float),
            initial_value=interval_hours,
            parse=float,
            validator=lambda v: (
                v >= MINIMAL_INTERVAL_HOURS,
                f"interval_hours must be at least {MINIMAL_INTERVAL_HOURS * 60:.0f} minutes"
            ),
        )
        
        # State for the time condition
        self._time_state = {
            "last_fire_time": None,
            "first_check": True,
        }
        self._fire_on_first_check = fire_on_first_check
        
        # Calculate poll interval (poll at least twice per interval, max 60s)
        initial_interval_seconds = interval_hours * 3600.0
        poll_seconds = min(initial_interval_seconds / 2, 60.0)
        
        super().__init__(
            event_name=event_name,
            condition_func=self._time_condition,
            message_builder=message_builder,
            message_builder_args=message_builder_args,
            message_builder_kwargs=message_builder_kwargs,
            editable_fields=[self._interval_field],
            poll_seconds=poll_seconds,
        )
    
    @property
    def interval_hours(self) -> float:
        """Get the current interval in hours."""
        return self._interval_field.value
    
    @interval_hours.setter
    def interval_hours(self, value: float) -> None:
        """Set the interval in hours."""
        self._interval_field.value = value
        self.edited = True  # Trigger immediate re-check
    
    def _time_condition(self) -> bool:
        """Return True when the interval has elapsed."""
        now = time.time()
        
        # Get current interval from editable field
        current_interval_seconds = self._interval_field.value * 3600.0
        
        # Handle first check
        if self._time_state["first_check"]:
            self._time_state["first_check"] = False
            if self._fire_on_first_check:
                self._time_state["last_fire_time"] = now
                return True
            else:
                self._time_state["last_fire_time"] = now
                return False
        
        # Check if interval has elapsed
        if self._time_state["last_fire_time"] is None:
            self._time_state["last_fire_time"] = now
            return False
        
        elapsed = now - self._time_state["last_fire_time"]
        if elapsed >= current_interval_seconds:
            self._time_state["last_fire_time"] = now
            return True
        
        return False
