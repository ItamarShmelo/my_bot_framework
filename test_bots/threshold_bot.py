"""Threshold bot testing ThresholdEvent class.

Tests:
- ThresholdEvent class (subclass of ActivateOnConditionEvent)
- Threshold property for runtime editing
- Cooldown mechanism
- Above/below threshold detection
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
    DialogHandler,
    UserInputDialog,
    ThresholdEvent,
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


def main():
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
    async def on_cpu_threshold_edited(result):
        """Handle CPU threshold edit."""
        bot = get_bot()
        chat_id_val = get_chat_id()
        log = get_logger()
        
        if is_cancelled(result):
            msg = TelegramTextMessage("❌ CPU threshold edit cancelled.")
            await msg.send(bot, chat_id_val, log)
            return
        
        try:
            new_value = float(result)
            cpu_event.threshold = new_value
            msg = TelegramTextMessage(
                f"✅ CPU threshold updated to <code>{cpu_event.threshold}</code>"
            )
            await msg.send(bot, chat_id_val, log)
        except ValueError as e:
            msg = TelegramTextMessage(f"❌ Invalid value: {e}")
            await msg.send(bot, chat_id_val, log)
    
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
    async def on_memory_threshold_edited(result):
        """Handle memory threshold edit."""
        bot = get_bot()
        chat_id_val = get_chat_id()
        log = get_logger()
        
        if is_cancelled(result):
            msg = TelegramTextMessage("❌ Memory threshold edit cancelled.")
            await msg.send(bot, chat_id_val, log)
            return
        
        try:
            new_value = float(result)
            memory_event.threshold = new_value
            msg = TelegramTextMessage(
                f"✅ Memory threshold updated to <code>{memory_event.threshold}</code>"
            )
            await msg.send(bot, chat_id_val, log)
        except ValueError as e:
            msg = TelegramTextMessage(f"❌ Invalid value: {e}")
            await msg.send(bot, chat_id_val, log)
    
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
    async def send_startup_and_run():
        startup_msg = TelegramTextMessage(
            f"🤖 <b>Threshold Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        await startup_msg.send(app.bot, app.chat_id, logger)
        logger.info("Starting threshold_bot...")
        await app.run()
    
    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
