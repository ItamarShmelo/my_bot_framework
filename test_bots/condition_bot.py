"""Condition bot testing ActivateOnConditionEvent and EditableAttribute.

Tests:
- ActivateOnConditionEvent with polling
- EditableAttribute for runtime parameter changes
- Condition function integration
"""

import asyncio
import logging
import random
import sys
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    ActivateOnConditionEvent,
    EditableAttribute,
    Condition,
    MessageBuilder,
)


def get_credentials() -> tuple[str, str]:
    """Get bot credentials from .token and .chat_id files in test_bots directory.

    Returns:
        Tuple of (token, chat_id) from credential files.

    Raises:
        RuntimeError: If .token or .chat_id files are missing or empty.
    """
    test_bots_dir = Path(__file__).resolve().parent
    token_file = test_bots_dir / ".token"
    chat_id_file = test_bots_dir / ".chat_id"

    if not token_file.exists() or not chat_id_file.exists():
        raise RuntimeError(
            "Missing credential files. Create .token and .chat_id files in test_bots directory."
        )

    token = token_file.read_text().strip()
    chat_id = chat_id_file.read_text().strip()

    if not token or not chat_id:
        raise RuntimeError(
            "Empty credential files. Ensure .token and .chat_id contain valid values."
        )
    return token, chat_id


# Simulated sensor value
_sensor_value = 50


def get_sensor_value() -> int:
    """Simulate a sensor reading that occasionally spikes."""
    global _sensor_value
    # Random walk with occasional spikes
    _sensor_value += random.randint(-5, 5)
    if random.random() < 0.1:  # 10% chance of spike
        _sensor_value += random.randint(20, 40)
    _sensor_value = max(0, min(100, _sensor_value))
    return _sensor_value


class SensorCondition(Condition):
    def __init__(self, threshold: int) -> None:
        threshold_attr = EditableAttribute(
            name="threshold",
            field_type=int,
            initial_value=threshold,
            parse=int,
            validator=lambda v: (0 <= v <= 100, "Threshold must be between 0 and 100"),
        )
        self.editable_attributes = [threshold_attr]
        self._edited = False

    def check(self) -> bool:
        """Check if sensor value exceeds threshold."""
        value = get_sensor_value()
        return value > self.get("threshold")


class SensorMessageBuilder(MessageBuilder):
    def __init__(self, condition: SensorCondition) -> None:
        self.editable_attributes = []
        self._edited = False
        self._condition = condition

    def build(self) -> str:
        """Build alert message with current value."""
        threshold = self._condition.get("threshold")
        return f"⚠️ Alert! Sensor value ({_sensor_value}) exceeded threshold ({threshold})!"


def main() -> None:
    """Run the condition test bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("condition_bot")

    token, chat_id = get_credentials()

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    condition = SensorCondition(threshold=80)
    builder = SensorMessageBuilder(condition)

    # Register condition event with editable attributes
    condition_event = ActivateOnConditionEvent(
        event_name="sensor_alert",
        condition=condition,
        message_builder=builder,
        poll_seconds=10.0,  # Check every 10 seconds
        fire_when_edited=False,  # Don't fire just because threshold was edited
    )
    app.register_event(condition_event)

    # Command to check current sensor value
    app.register_command(SimpleCommand(
        command="/sensor",
        description="Show current sensor value",
        message_builder=lambda: f"Current sensor value: {_sensor_value}",
    ))

    # Command to show current threshold
    app.register_command(SimpleCommand(
        command="/threshold",
        description="Show current alert threshold",
        message_builder=lambda: f"Current threshold: {condition_event.get('condition.threshold')}",
    ))

    # Register info command
    info_text = (
        "<b>Condition Bot</b>\n\n"
        "Tests condition-based events:\n"
        "• ActivateOnConditionEvent with polling\n"
        "• EditableAttribute for runtime parameter changes\n"
        "• Condition/MessageBuilder interfaces\n\n"
        "Simulates a sensor that triggers alerts when exceeding threshold."
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    # Send startup message and run
    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"🤖 <b>Condition Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting condition_bot...")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
