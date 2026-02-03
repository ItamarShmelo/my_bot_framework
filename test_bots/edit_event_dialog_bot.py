"""EditEventDialog bot demonstrating event editing via inline keyboard.

Tests:
- EditEventDialog with boolean and numeric fields
- Cross-field validation (limit_min < limit_max)
- Staged edits applied only on Done
- Manual cross-field validation pattern (educational)
"""

import asyncio
import logging
import os
import random
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

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
    EditEventDialog,
    SequenceDialog,
    UserInputDialog,
    DialogHandler,
    is_cancelled,
    get_app,
)


def get_credentials() -> Tuple[str, str]:
    """Get bot credentials from environment variables.
    
    Returns:
        Tuple of (token, chat_id) from environment variables.
    
    Raises:
        RuntimeError: If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are not set.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        raise RuntimeError(
            "Missing environment variables. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )
    return token, chat_id


# Simulated sensor value
_sensor_value = 50.0


def get_sensor_value() -> float:
    """Simulate a sensor reading with random fluctuation."""
    global _sensor_value
    _sensor_value += random.uniform(-5.0, 5.0)
    _sensor_value = max(0.0, min(100.0, _sensor_value))
    return _sensor_value


class RangeCondition(Condition):
    """Condition that checks if sensor value is within a range."""
    
    def __init__(self, limit_min: float, limit_max: float, log_scale: bool) -> None:
        """Initialize with min/max limits and optional log scale."""
        limit_min_attr = EditableAttribute.float(
            "limit_min",
            limit_min,
            min_val=0.0,
            max_val=100.0,
        )
        limit_max_attr = EditableAttribute.float(
            "limit_max",
            limit_max,
            min_val=0.0,
            max_val=100.0,
        )
        log_scale_attr = EditableAttribute.bool("log_scale", log_scale)
        self.editable_attributes = [limit_min_attr, limit_max_attr, log_scale_attr]
        self._edited = False
    
    def check(self) -> bool:
        """Check if sensor value is outside the range (triggers alert)."""
        value = get_sensor_value()
        limit_min = self.get("limit_min")
        limit_max = self.get("limit_max")
        return value < limit_min or value > limit_max


class RangeAlertBuilder(MessageBuilder):
    """Message builder for range alerts."""
    
    def __init__(self, condition: RangeCondition) -> None:
        """Initialize with reference to condition for accessing limits."""
        self.editable_attributes = []
        self._edited = False
        self._condition = condition
    
    def build(self) -> str:
        """Build alert message with current value and range."""
        limit_min = self._condition.get("limit_min")
        limit_max = self._condition.get("limit_max")
        log_scale = self._condition.get("log_scale")
        scale_text = "log" if log_scale else "linear"
        
        return (
            f"⚠️ <b>Range Alert</b>\n\n"
            f"Sensor value: <code>{_sensor_value:.1f}</code>\n"
            f"Valid range: <code>{limit_min:.1f} - {limit_max:.1f}</code>\n"
            f"Scale: <code>{scale_text}</code>"
        )


def main() -> None:
    """Main entry point for edit_event_dialog_bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("edit_event_dialog_bot")
    
    token, chat_id = get_credentials()
    
    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )
    
    # Create condition event with editable attributes
    condition = RangeCondition(limit_min=20.0, limit_max=80.0, log_scale=False)
    builder = RangeAlertBuilder(condition=condition)
    range_event = ActivateOnConditionEvent(
        event_name="range_alert",
        condition=condition,
        message_builder=builder,
        poll_seconds=30.0,  # Check every 30 seconds
        fire_when_edited=False,  # Don't fire just because settings were edited
    )
    app.register_event(range_event)
    
    # --- Commands to view current values ---
    
    app.register_command(SimpleCommand(
        command="/sensor",
        description="Show current sensor value",
        message_builder=lambda: f"Current sensor value: <code>{_sensor_value:.1f}</code>",
    ))
    
    def get_settings_text() -> str:
        """Build settings display text.
        
        Returns:
            HTML formatted text showing current settings.
        """
        limit_min = range_event.get("condition.limit_min")
        limit_max = range_event.get("condition.limit_max")
        log_scale = range_event.get("condition.log_scale")
        scale_text = "log" if log_scale else "linear"
        return (
            "<b>Current Settings</b>\n\n"
            f"Limit Min: <code>{limit_min:.1f}</code>\n"
            f"Limit Max: <code>{limit_max:.1f}</code>\n"
            f"Log Scale: <code>{log_scale}</code> ({scale_text})"
        )
    
    app.register_command(SimpleCommand(
        command="/settings",
        description="Show current settings",
        message_builder=get_settings_text,
    ))
    
    # --- APPROACH 1: EditEventDialog with validator (recommended) ---
    
    def validate_limits(context: Dict[str, Any]) -> Tuple[bool, str]:
        """Cross-field validation: ensure limit_min < limit_max.
        
        This validator runs after each field edit. It receives the context
        dict containing all staged edits, merged with current event values.
        
        Args:
            context: Dict of staged edits {field_name: new_value}
        
        Returns:
            (is_valid, error_message) tuple
        """
        # Get values from context (staged edits) or fall back to event values
        limit_min = context.get(
            "condition.limit_min",
            range_event.get("condition.limit_min"),
        )
        limit_max = context.get(
            "condition.limit_max",
            range_event.get("condition.limit_max"),
        )
        
        if limit_min is not None and limit_max is not None:
            if limit_min >= limit_max:
                return False, f"limit_min ({limit_min:.1f}) must be < limit_max ({limit_max:.1f})"
        return True, ""
    
    # Create EditEventDialog with cross-field validation
    edit_dialog = EditEventDialog(range_event, validator=validate_limits)
    
    async def on_edit_complete(result: Any) -> None:
        """Handle edit dialog completion.
        
        Args:
            result: Dialog result containing edited fields or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ Edit cancelled. No changes applied.")
            return
        
        # Result contains all fields that were edited
        if result:
            edited_fields = ", ".join(result.keys())
            await get_app().send_messages(
                f"✅ Settings updated!\n\n"
                f"Modified fields: {edited_fields}\n\n"
                f"{get_settings_text()}"
            )
        else:
            await get_app().send_messages("ℹ️ No changes made.")
    
    handled_edit_dialog = DialogHandler(edit_dialog, on_complete=on_edit_complete)
    
    app.register_command(DialogCommand(
        command="/edit",
        description="Edit event settings (with cross-field validation)",
        dialog=handled_edit_dialog,
    ))
    
    # --- APPROACH 2: Manual cross-field validation (educational) ---
    # This demonstrates how to achieve similar validation without EditEventDialog
    # using closures, context, and UserInputDialog validators.
    
    def make_max_validator(get_min_value: Callable[[], float]):
        """Create a validator closure that ensures value > min.
        
        This pattern shows how closures can capture external state
        to enable cross-field validation in sequential dialogs.
        
        Args:
            get_min_value: Callable that returns the current min value
        
        Returns:
            Validator function for UserInputDialog
        """
        def validator(value_str: str) -> Tuple[bool, str]:
            try:
                max_val = float(value_str)
            except ValueError:
                return False, "Must be a number"
            
            if max_val < 0 or max_val > 100:
                return False, "Must be between 0 and 100"
            
            min_val = get_min_value()
            if min_val is not None and max_val <= min_val:
                return False, f"Must be > limit_min ({min_val:.1f})"
            return True, ""
        return validator
    
    def make_min_validator():
        """Create validator for min value (simple range check)."""
        def validator(value_str: str) -> Tuple[bool, str]:
            try:
                min_val = float(value_str)
            except ValueError:
                return False, "Must be a number"
            
            if min_val < 0 or min_val > 100:
                return False, "Must be between 0 and 100"
            return True, ""
        return validator
    
    # SequenceDialog with cross-field validation via closures
    # After limit_min is entered, it's stored in context["limit_min"]
    # The limit_max validator reads from the sequence's context
    manual_edit_sequence = SequenceDialog([
        ("limit_min", UserInputDialog(
            lambda: f"Enter limit_min (current: {range_event.get('condition.limit_min'):.1f}):",
            validator=make_min_validator(),
        )),
        ("limit_max", UserInputDialog(
            lambda: f"Enter limit_max (current: {range_event.get('condition.limit_max'):.1f}):",
            # Closure reads from sequence context via lambda
            validator=make_max_validator(
                lambda: float(manual_edit_sequence.context.get("limit_min", 0))
            ),
        )),
    ])
    
    async def on_manual_edit_complete(result: Any) -> None:
        """Handle manual edit sequence completion.
        
        Args:
            result: Dialog result containing edited fields or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ Manual edit cancelled.")
            return
        
        # Apply edits manually
        try:
            if "limit_min" in result:
                range_event.edit("condition.limit_min", result["limit_min"])
            if "limit_max" in result:
                range_event.edit("condition.limit_max", result["limit_max"])
            
            await get_app().send_messages(
                f"✅ Manual edit complete!\n\n{get_settings_text()}"
            )
        except ValueError as e:
            await get_app().send_messages(f"❌ Error applying edits: {e}")
    
    handled_manual_dialog = DialogHandler(
        manual_edit_sequence,
        on_complete=on_manual_edit_complete,
    )
    
    app.register_command(DialogCommand(
        command="/manual_edit",
        description="Edit limits manually (demonstrates closure pattern)",
        dialog=handled_manual_dialog,
    ))
    
    # --- Info command ---
    
    info_text = (
        "<b>EditEventDialog Bot</b>\n\n"
        "Tests the EditEventDialog class:\n"
        "• Boolean fields with True/False toggle\n"
        "• Numeric fields with text input\n"
        "• Cross-field validation (limit_min &lt; limit_max)\n"
        "• Staged edits applied only on Done\n\n"
        "<b>Commands:</b>\n"
        "/sensor - Show current sensor value\n"
        "/settings - Show current settings\n"
        "/edit - Edit settings with EditEventDialog\n"
        "/manual_edit - Edit using closure pattern (educational)"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))
    
    # Send startup message and run
    async def send_startup_and_run() -> None:
        """Send startup message and run the bot."""
        await app.send_messages(
            f"🤖 <b>EditEventDialog Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting edit_event_dialog_bot...")
        await app.run()
    
    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
