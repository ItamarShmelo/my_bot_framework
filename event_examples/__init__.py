"""Event examples and factories for common patterns.

This package provides:
- Event subclasses (TimeEvent, ThresholdEvent) for class-based usage
- Factory functions (create_threshold_event, create_file_change_event) for functional usage
"""

from .time_event import TimeEvent
from .threshold_event import ThresholdEvent
from .factories import (
    create_threshold_event,
    create_file_change_event,
)

__all__ = [
    # Event subclasses
    "TimeEvent",
    "ThresholdEvent",
    # Factory functions
    "create_threshold_event",
    "create_file_change_event",
]
