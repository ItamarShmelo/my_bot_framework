"""Threshold bot testing ThresholdEvent class.

Tests:
- ThresholdEvent class (subclass of ActivateOnConditionEvent)
- Threshold property for runtime editing
- Cooldown mechanism
- Above/below threshold detection
"""

import asyncio
import logging
import random
import sys
from pathlib import Path
from typing import Any

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    DialogCommand,
    DialogHandler,
    UserInputDialog,
    ThresholdEvent,
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


# Simulated metrics
_cpu_value = 50.0
_memory_value = 60.0


def get_cpu_value() -> float:
    """Simulate CPU usage with random walk."""
    global _cpu_value
    _cpu_value += random.uniform(-5, 5)
    if random.random() < 0.1:  # 10% chance of spike
        _cpu_value += random.uniform(15, 30)
    _cpu_value = max(0, min(100, _cpu_value))
    return _cpu_value


def get_memory_value() -> float:
    """Simulate memory usage with gradual increase."""
    global _memory_value
    _memory_value += random.uniform(-2, 3)  # Slight upward bias
    _memory_value = max(0, min(100, _memory_value))
    return _memory_value


def main() -> None:
    """Run the threshold test bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("threshold_bot")

    token, chat_id = get_credentials()

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Create CPU threshold event
    cpu_event = ThresholdEvent(
        event_name="high_cpu",
        value_getter=get_cpu_value,
        threshold=80.0,
        message_builder=lambda: f"🔥 <b>High CPU Alert!</b>\nCurrent: <code>{_cpu_value:.1f}%</code>",
        above=True,
        poll_seconds=5.0,
        cooldown_seconds=30.0,  # 30 second cooldown
    )
    app.register_event(cpu_event)

    # Create memory threshold event
    memory_event = ThresholdEvent(
        event_name="high_memory",
        value_getter=get_memory_value,
        threshold=75.0,
        message_builder=lambda: f"💾 <b>High Memory Alert!</b>\nCurrent: <code>{_memory_value:.1f}%</code>",
        above=True,
        poll_seconds=5.0,
        cooldown_seconds=30.0,
    )
    app.register_event(memory_event)

    # Command to show current values
    app.register_command(SimpleCommand(
        command="/status",
        description="Show current CPU and memory values",
        message_builder=lambda: (
            f"<b>Current Status</b>\n\n"
            f"CPU: <code>{_cpu_value:.1f}%</code> (threshold: {cpu_event.threshold})\n"
            f"Memory: <code>{_memory_value:.1f}%</code> (threshold: {memory_event.threshold})"
        ),
    ))

    # Command to show thresholds
    app.register_command(SimpleCommand(
        command="/thresholds",
        description="Show current thresholds",
        message_builder=lambda: (
            f"<b>Thresholds</b>\n\n"
            f"CPU: <code>{cpu_event.threshold}</code>\n"
            f"Memory: <code>{memory_event.threshold}</code>"
        ),
    ))

    # Dialog command to edit CPU threshold
    async def on_cpu_threshold_edited(result: Any) -> None:
        """Handle CPU threshold edit.
        
        Args:
            result: The dialog result containing the new threshold value or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ CPU threshold edit cancelled.")
            return

        try:
            new_value = float(result)
            cpu_event.threshold = new_value
            await get_app().send_messages(
                f"✅ CPU threshold updated to <code>{cpu_event.threshold}</code>"
            )
        except ValueError as e:
            await get_app().send_messages(f"❌ Invalid value: {e}")

    cpu_dialog = DialogHandler(
        UserInputDialog(
            "Enter new CPU threshold (0-100):",
            validator=lambda v: (
                v.replace(".", "", 1).isdigit() and 0 <= float(v) <= 100,
                "Enter a number between 0 and 100"
            ),
        ),
        on_complete=on_cpu_threshold_edited,
    )

    app.register_command(DialogCommand(
        command="/edit_cpu",
        description="Edit CPU threshold",
        dialog=cpu_dialog,
    ))

    # Dialog command to edit memory threshold
    async def on_memory_threshold_edited(result: Any) -> None:
        """Handle memory threshold edit.
        
        Args:
            result: The dialog result containing the new threshold value or CANCELLED.
        """
        if is_cancelled(result):
            await get_app().send_messages("❌ Memory threshold edit cancelled.")
            return

        try:
            new_value = float(result)
            memory_event.threshold = new_value
            await get_app().send_messages(
                f"✅ Memory threshold updated to <code>{memory_event.threshold}</code>"
            )
        except ValueError as e:
            await get_app().send_messages(f"❌ Invalid value: {e}")

    memory_dialog = DialogHandler(
        UserInputDialog(
            "Enter new memory threshold (0-100):",
            validator=lambda v: (
                v.replace(".", "", 1).isdigit() and 0 <= float(v) <= 100,
                "Enter a number between 0 and 100"
            ),
        ),
        on_complete=on_memory_threshold_edited,
    )

    app.register_command(DialogCommand(
        command="/edit_memory",
        description="Edit memory threshold",
        dialog=memory_dialog,
    ))

    # Info command
    info_text = (
        "<b>Threshold Bot</b>\n\n"
        "Tests threshold-based events:\n"
        "• <code>ThresholdEvent</code> class\n"
        "• <code>threshold</code> property for runtime editing\n"
        "• Cooldown mechanism (30s)\n"
        "• Above/below detection\n\n"
        "<b>Commands:</b>\n"
        "/status - Show current CPU/memory values\n"
        "/thresholds - Show current thresholds\n"
        "/edit_cpu - Edit CPU threshold\n"
        "/edit_memory - Edit memory threshold"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))

    # Send startup message and run
    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"🤖 <b>Threshold Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("send_startup_and_run: starting")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
