# My Bot Framework

A modular, event-driven Telegram bot framework built on `python-telegram-bot`.

## Features

- **Singleton Bot Application** - Centralized bot lifecycle management
- **Event System** - Time-based and condition-based event triggers
- **Command Handling** - Simple commands and interactive dialog commands
- **Message Queue** - Async message sending with automatic chunking
- **Interactive Dialogs** - Multi-step conversations with inline keyboards
- **Editable Parameters** - Runtime-configurable event parameters

## Installation

```bash
pip install python-telegram-bot
```

## Quick Start

```python
import asyncio
import logging
from my_bot_framework import BotApplication, SimpleCommand, TimeEvent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the bot
app = BotApplication.initialize(
    token="YOUR_BOT_TOKEN",
    chat_id="YOUR_CHAT_ID",
    logger=logger,
)

# Register a simple command
app.register_command(SimpleCommand(
    command="/hello",
    description="Say hello",
    message_builder=lambda: "Hello, World!",
))

# Register a time-based event (runs every hour)
app.register_event(TimeEvent(
    event_name="hourly_update",
    interval_hours=1.0,
    message_builder=lambda: "Hourly ping!",
    fire_on_first_check=True,
))

# Run the bot
asyncio.run(app.run())
```

## Core Components

### BotApplication

The singleton entry point for the framework. Manages:
- Bot instance and credentials
- Message queue for outgoing messages
- Event and command registration
- Graceful shutdown via `/terminate`

```python
from my_bot_framework import BotApplication, get_app, get_bot, get_logger

# Initialize once
app = BotApplication.initialize(token="...", chat_id="...", logger=logger)

# Access from anywhere
app = get_app()
bot = get_bot()
logger = get_logger()
```

### Events

Events run continuously and enqueue messages based on triggers.

#### TimeEvent

Emits messages at a fixed interval:

```python
from my_bot_framework import TimeEvent

event = TimeEvent(
    event_name="status_check",
    interval_hours=0.5,  # Every 30 minutes (minimum 5 minutes)
    message_builder=get_status,
    fire_on_first_check=True,  # Emit immediately on start
)
app.register_event(event)
```

#### ActivateOnConditionEvent

Emits messages when a condition becomes truthy:

```python
from my_bot_framework import ActivateOnConditionEvent, EditableField

def check_disk_full():
    return disk_usage() > 90

event = ActivateOnConditionEvent(
    event_name="disk_alert",
    condition_func=check_disk_full,
    message_builder=lambda: "Disk usage critical!",
    poll_seconds=60.0,
    editable_fields=[
        EditableField(
            name="threshold",
            field_type=int,
            initial_value=90,
            parse=int,
        ),
    ],
)
app.register_event(event)
```

### Commands

Commands respond to user input via Telegram messages.

#### SimpleCommand

Immediate response command:

```python
from my_bot_framework import SimpleCommand

cmd = SimpleCommand(
    command="/status",
    description="Show current status",
    message_builder=get_status_message,
)
app.register_command(cmd)
```

#### DialogCommand

Multi-step interactive command with inline keyboards:

```python
from my_bot_framework import DialogCommand
from my_dialogs import SettingsDialog

cmd = DialogCommand(
    command="/settings",
    description="Configure settings",
    dialog=SettingsDialog(),
)
app.register_command(cmd)
```

### Dialogs

The framework provides built-in dialog types for common interactions:

**Leaf Dialogs** (atomic single-step):
- `ChoiceDialog` - User selects from keyboard options
- `UserInputDialog` - User enters text (with optional validation)
- `ConfirmDialog` - Yes/No prompt

**Composite Dialogs** (multi-step):
- `SequenceDialog` - Run dialogs in order
- `BranchDialog` - Condition-based branching
- `ChoiceBranchDialog` - User selects branch
- `LoopDialog` - Repeat until exit condition
- `DialogHandler` - Wrap dialog with completion callback

```python
from my_bot_framework import (
    ChoiceDialog, UserInputDialog, ConfirmDialog,
    SequenceDialog, DialogHandler, DialogCommand,
    CANCELLED, is_cancelled,
)

# Simple choice dialog
color_dialog = ChoiceDialog("Pick a color:", [
    ("Red", "red"),
    ("Green", "green"),
    ("Blue", "blue"),
])

# Multi-step sequence
survey_dialog = SequenceDialog([
    ("name", UserInputDialog("What is your name?")),
    ("rating", ChoiceDialog("Rate our service:", [
        ("5 Stars", "5"),
        ("4 Stars", "4"),
        ("3 Stars", "3"),
    ])),
    ("recommend", ConfirmDialog("Would you recommend us?")),
])

# DialogHandler with completion callback
def on_complete(result):
    if is_cancelled(result):
        print("User cancelled")
    else:
        print(f"Survey complete: {result}")

handled_dialog = DialogHandler(survey_dialog, on_complete=on_complete)

# Register as command
app.register_command(DialogCommand("/survey", "Take survey", handled_dialog))
```

#### Cancellation Handling

Use the `CANCELLED` sentinel for unambiguous cancellation detection:

```python
from my_bot_framework import CANCELLED, is_cancelled

def on_complete(result):
    # Using helper function
    if is_cancelled(result):
        print("Cancelled!")
        return
    
    # Or direct comparison
    if result is CANCELLED:
        print("Cancelled!")
        return
    
    print(f"Got result: {result}")
```

### Message Types

The framework provides several message wrappers:

```python
from my_bot_framework import (
    TelegramTextMessage,
    TelegramImageMessage,
    TelegramOptionsMessage,
    TelegramEditMessage,
)

# Plain text (auto-chunked for long messages)
TelegramTextMessage("Hello, world!")

# Image with caption
TelegramImageMessage("/path/to/image.png", caption="My image")

# Message with inline keyboard
TelegramOptionsMessage("Choose an option:", keyboard_markup)

# Edit existing message
TelegramEditMessage(message_id=123, text="Updated text")
```

## Built-in Commands

The framework automatically registers:

- `/terminate` - Gracefully shut down the bot
- `/commands` - List all available commands

## Message Builders

Message builders are callables that return message content. They can return:

- `str` - Plain text message
- `TelegramMessage` - Any message type
- `List[TelegramMessage]` - Multiple messages
- `None` - No message sent

```python
def status_builder():
    return f"Status: OK\nUptime: {get_uptime()}"

# Or return a TelegramMessage directly
def image_builder():
    return TelegramImageMessage("/path/to/chart.png")
```

## Editable Fields

Runtime-editable parameters with validation:

```python
from my_bot_framework import EditableField

field = EditableField(
    name="threshold",
    field_type=int,
    initial_value=100,
    parse=int,  # String parser
    validator=lambda v: (v > 0, "Must be positive"),
)

# Update via string input
field.value = "150"  # Parsed and validated

# Or set directly
field.value = 200
```

## Utilities

### HTML Message Formatting

```python
from my_bot_framework import format_message_html

html = format_message_html([
    ("Status", "Running", None),
    ("Memory", 85.5, ".1f"),
    ("Uptime", "2 days", None),
])
# Returns formatted <pre> block with aligned labels
```

### Message Chunking

Long messages are automatically chunked to fit Telegram's message limit:

```python
from my_bot_framework import divide_message_to_chunks

chunks = divide_message_to_chunks(long_text, chunk_size=4000)
```

## License

MIT
