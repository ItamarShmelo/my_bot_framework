"""Editable bot demonstrating EditableAttribute and EditableMixin.

Tests:
- EditableAttribute creation with parsing and validation
- Editing fields via DialogCommand
- EditableMixin.edited flag for immediate re-check
- Dynamic kwargs from editable fields
"""

import asyncio
import logging
import os
import random
import sys
from pathlib import Path

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
    ChoiceDialog,
    UserInputDialog,
    SequenceDialog,
    DialogHandler,
    is_cancelled,
    get_bot,
    get_chat_id,
    get_logger,
    TelegramTextMessage,
)


def get_credentials():
    """Get bot credentials from environment variables."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        raise RuntimeError(
            "Missing environment variables. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
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
    

class AlertMessageBuilder(MessageBuilder):
    def __init__(self, condition: SensorCondition, alert_level: str) -> None:
        alert_level_attr = EditableAttribute(
            name="alert_level",
            field_type=str,
            initial_value=alert_level,
            parse=str,
            validator=lambda v: (
                v in ("info", "warning", "critical"),
                "Level must be: info, warning, or critical"
            ),
        )
        self.editable_attributes = [alert_level_attr]
        self._edited = False
        self._condition = condition
    
    def build(self) -> str:
        """Build alert message with current value and level."""
        alert_level = self.get("alert_level")
        threshold = self._condition.get("threshold")
        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(alert_level, "⚠️")
        return (
            f"{icon} <b>{alert_level.upper()}</b>\n\n"
            f"Sensor value: <code>{_sensor_value}</code>\n"
            f"Threshold: <code>{threshold}</code>"
        )
    

def main():
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
    
    app.register_command(SimpleCommand(
        command="/settings",
        description="Show current settings",
        message_builder=lambda: (
            "<b>Current Settings</b>\n\n"
            f"Threshold: <code>{sensor_event.get('condition.threshold')}</code>\n"
            f"Alert Level: <code>{sensor_event.get('builder.alert_level')}</code>"
        ),
    ))
    
    # --- Dialog command to edit threshold ---
    
    async def on_threshold_edited(result):
        """Handle threshold edit completion."""
        bot = get_bot()
        chat_id = get_chat_id()
        log = get_logger()
        
        if is_cancelled(result):
            msg = TelegramTextMessage("❌ Threshold edit cancelled.")
            await msg.send(bot, chat_id, log)
            return
        
        try:
            sensor_event.edit("condition.threshold", result)
            
            msg = TelegramTextMessage(
                f"✅ Threshold updated to <code>{sensor_event.get('condition.threshold')}</code>"
            )
            await msg.send(bot, chat_id, log)
        except ValueError as e:
            msg = TelegramTextMessage(f"❌ Invalid threshold: {e}")
            await msg.send(bot, chat_id, log)
    
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
    
    async def on_level_edited(result):
        """Handle alert level edit completion."""
        bot = get_bot()
        chat_id = get_chat_id()
        log = get_logger()
        
        if is_cancelled(result):
            msg = TelegramTextMessage("❌ Alert level edit cancelled.")
            await msg.send(bot, chat_id, log)
            return
        
        sensor_event.edit("builder.alert_level", result)
        
        icons = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}
        icon = icons.get(sensor_event.get("builder.alert_level"), "")
        msg = TelegramTextMessage(
            f"✅ Alert level updated to {icon} <code>{sensor_event.get('builder.alert_level')}</code>"
        )
        await msg.send(bot, chat_id, log)
    
    level_dialog = DialogHandler(
        ChoiceDialog("Select alert level:", [
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
    
    async def on_all_edited(result):
        """Handle combined settings edit."""
        bot = get_bot()
        chat_id = get_chat_id()
        log = get_logger()
        
        if is_cancelled(result):
            msg = TelegramTextMessage("❌ Settings edit cancelled.")
            await msg.send(bot, chat_id, log)
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
            msg = TelegramTextMessage(f"⚠️ Settings updated with errors:\n{error_text}")
        else:
            msg = TelegramTextMessage(
                f"✅ <b>Settings Updated</b>\n\n"
                f"Threshold: <code>{sensor_event.get('condition.threshold')}</code>\n"
                f"Alert Level: {icon} <code>{sensor_event.get('builder.alert_level')}</code>"
            )
        await msg.send(bot, chat_id, log)
    
    combined_dialog = DialogHandler(
        SequenceDialog([
            ("threshold", UserInputDialog(
                "Enter new threshold (0-100):",
                validator=lambda v: (
                    v.isdigit() and 0 <= int(v) <= 100,
                    "Enter a number between 0 and 100"
                ),
            )),
            ("level", ChoiceDialog("Select alert level:", [
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
        "• <code>EditableAttribute</code> - Type parsing and validation\n"
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
    async def send_startup_and_run():
        startup_msg = TelegramTextMessage(
            f"🤖 <b>Editable Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        await startup_msg.send(app.bot, app.chat_id, logger)
        logger.info("Starting editable_bot...")
        await app.run()
    
    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
