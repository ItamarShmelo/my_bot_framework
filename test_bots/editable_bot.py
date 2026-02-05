"""Editable bot demonstrating EditableAttribute and EditableMixin.

Tests:
- EditableAttribute creation with parsing and validation
- Editing fields via DialogCommand
- EditableMixin.edited flag for immediate re-check
- Dynamic kwargs from editable fields
"""

import asyncio
import logging
import random
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    DialogCommand,
    ActivateOnConditionEvent,
    EditableAttribute,
    Condition,
    MessageBuilder,
    InlineKeyboardChoiceDialog,
    UserInputDialog,
    SequenceDialog,
    DialogHandler,
    is_cancelled,
    get_app,
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
        threshold_attr = EditableAttribute.int(
            "threshold",
            threshold,
            min_val=0,
            max_val=100,
        )
        self.editable_attributes = [threshold_attr]
        self._edited = False

    def check(self) -> bool:
        """Check if sensor value exceeds threshold."""
        value = get_sensor_value()
        return value > self.get("threshold")


class AlertMessageBuilder(MessageBuilder):
    def __init__(self, condition: SensorCondition, alert_level: str) -> None:
        alert_level_attr = EditableAttribute.str(
            "alert_level",
            alert_level,
            choices=["info", "warning", "critical"],
        )
        # Optional int: None means unlimited, otherwise max number of alerts
        max_alerts_attr = EditableAttribute.int(
            "max_alerts",
            None,  # None = unlimited
            optional=True,
            min_val=1,
        )
        self.editable_attributes = [alert_level_attr, max_alerts_attr]
        self._edited = False
        self._condition = condition
        self._alert_count = 0

    def build(self) -> Optional[str]:
        """Build alert message with current value and level."""
        max_alerts = self.get("max_alerts")

        # Check if we've hit the limit (if set)
        if max_alerts is not None and self._alert_count >= max_alerts:
            return None  # Suppress alert

        self._alert_count += 1

        alert_level = self.get("alert_level")
        threshold = self._condition.get("threshold")
        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(alert_level, "⚠️")

        limit_text = f" ({self._alert_count}/{max_alerts})" if max_alerts else ""
        return (
            f"{icon} <b>{alert_level.upper()}</b>{limit_text}\n\n"
            f"Sensor value: <code>{_sensor_value}</code>\n"
            f"Threshold: <code>{threshold}</code>"
        )


def main() -> None:
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("editable_bot")

    token, chat_id = get_credentials()

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Register condition event with editable attributes
    condition = SensorCondition(threshold=80)
    builder = AlertMessageBuilder(condition=condition, alert_level="warning")
    sensor_event = ActivateOnConditionEvent(
        event_name="sensor_alert",
        condition=condition,
        message_builder=builder,
        poll_seconds=15.0,  # Check every 15 seconds
        fire_when_edited=False,  # Don't fire just because settings were edited
    )
    app.register_event(sensor_event)

    # --- Commands to view current values ---

    app.register_command(SimpleCommand(
        command="/sensor",
        description="Show current sensor value",
        message_builder=lambda: f"Current sensor value: <code>{_sensor_value}</code>",
    ))

    def get_settings_text() -> str:
        max_alerts = sensor_event.get("builder.max_alerts")
        max_alerts_text = "unlimited" if max_alerts is None else str(max_alerts)
        return (
            "<b>Current Settings</b>\n\n"
            f"Threshold: <code>{sensor_event.get('condition.threshold')}</code>\n"
            f"Alert Level: <code>{sensor_event.get('builder.alert_level')}</code>\n"
            f"Max Alerts: <code>{max_alerts_text}</code>"
        )

    app.register_command(SimpleCommand(
        command="/settings",
        description="Show current settings",
        message_builder=get_settings_text,
    ))

    # --- Dialog command to edit threshold ---

    async def on_threshold_edited(result: Any) -> None:
        """Handle threshold edit completion.
        
        Args:
            result: The dialog result containing the new threshold value or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ Threshold edit cancelled.")
            return

        try:
            sensor_event.edit("condition.threshold", result)
            await get_app().send_messages(
                f"✅ Threshold updated to <code>{sensor_event.get('condition.threshold')}</code>"
            )
        except ValueError as e:
            await get_app().send_messages(f"❌ Invalid threshold: {e}")

    threshold_dialog = DialogHandler(
        UserInputDialog(
            lambda: (
                "Enter new threshold (current: "
                f"{sensor_event.get('condition.threshold')}, range 0-100):"
            ),
            validator=lambda v: (
                v.isdigit() and 0 <= int(v) <= 100,
                "Enter a number between 0 and 100"
            ),
        ),
        on_complete=on_threshold_edited,
    )

    app.register_command(DialogCommand(
        command="/edit_threshold",
        description="Edit the alert threshold",
        dialog=threshold_dialog,
    ))

    # --- Dialog command to edit alert level ---

    async def on_level_edited(result: Any) -> None:
        """Handle alert level edit completion.
        
        Args:
            result: The dialog result containing the new alert level or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ Alert level edit cancelled.")
            return

        sensor_event.edit("builder.alert_level", result)

        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(sensor_event.get("builder.alert_level"), "")
        await get_app().send_messages(
            f"✅ Alert level updated to {icon} <code>{sensor_event.get('builder.alert_level')}</code>"
        )

    level_dialog = DialogHandler(
        InlineKeyboardChoiceDialog("Select alert level:", [
            ("ℹ️ Info", "info"),
            ("⚠️ Warning", "warning"),
            ("🚨 Critical", "critical"),
        ]),
        on_complete=on_level_edited,
    )

    app.register_command(DialogCommand(
        command="/edit_level",
        description="Edit the alert level",
        dialog=level_dialog,
    ))

    # --- Combined edit dialog ---

    async def on_all_edited(result: Any) -> None:
        """Handle combined settings edit.
        
        Args:
            result: The dialog result containing edited fields as a dict or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ Settings edit cancelled.")
            return

        # Result is a dict: {"threshold": "75", "level": "critical"}
        new_threshold = result.get("threshold")
        new_level = result.get("level")
        errors = []

        if new_threshold:
            try:
                sensor_event.edit("condition.threshold", new_threshold)
            except ValueError as e:
                errors.append(f"Threshold: {e}")

        if new_level:
            try:
                sensor_event.edit("builder.alert_level", new_level)
            except ValueError as e:
                errors.append(f"Alert Level: {e}")

        # Build confirmation message
        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(sensor_event.get("builder.alert_level"), "")

        if errors:
            error_text = "\n".join(f"• {e}" for e in errors)
            await get_app().send_messages(f"⚠️ Settings updated with errors:\n{error_text}")
        else:
            await get_app().send_messages(
                f"✅ <b>Settings Updated</b>\n\n"
                f"Threshold: <code>{sensor_event.get('condition.threshold')}</code>\n"
                f"Alert Level: {icon} <code>{sensor_event.get('builder.alert_level')}</code>"
            )

    combined_dialog = DialogHandler(
        SequenceDialog([
            ("threshold", UserInputDialog(
                "Enter new threshold (0-100):",
                validator=lambda v: (
                    v.isdigit() and 0 <= int(v) <= 100,
                    "Enter a number between 0 and 100"
                ),
            )),
            ("level", InlineKeyboardChoiceDialog("Select alert level:", [
                ("ℹ️ Info", "info"),
                ("⚠️ Warning", "warning"),
                ("🚨 Critical", "critical"),
            ])),
        ]),
        on_complete=on_all_edited,
    )

    app.register_command(DialogCommand(
        command="/edit_all",
        description="Edit all settings",
        dialog=combined_dialog,
    ))

    # --- Info command ---

    info_text = (
        "<b>Editable Bot</b>\n\n"
        "Tests runtime-editable parameters:\n"
        "• <code>EditableAttribute</code> factory methods (int, str, optional=True)\n"
        "• <code>EditableMixin</code> - Edited flag for immediate re-check\n"
        "• Dialog-based editing of event parameters\n\n"
        "<b>Commands:</b>\n"
        "/sensor - Show current sensor value\n"
        "/settings - Show current settings\n"
        "/edit_threshold - Edit threshold via dialog\n"
        "/edit_level - Edit alert level via dialog\n"
        "/edit_all - Edit all settings at once"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    # Send startup message and run
    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"🤖 <b>Editable Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting editable_bot...")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
if __name__ == "__main__":
    main()
