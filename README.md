# My Bot Framework

A modular, event-driven Telegram bot framework built on `python-telegram-bot`.

## Features

- **Singleton Bot Application** - Centralized bot lifecycle management
- **Event System** - Time-based and condition-based event triggers
- **Command Handling** - Simple commands and interactive dialog commands
- **Direct Message Sending** - Async message sending with automatic chunking
- **Interactive Dialogs** - Multi-step conversations with inline keyboards
- **Editable Parameters** - Runtime-configurable event parameters
- **Resilient Polling** - Automatic handling of transient Telegram network errors

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for package and virtual environment management.

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and sync dependencies
git clone <repo-url>
cd my_bot_framework
uv sync
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
- Direct message sending for outgoing messages
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

#### Sending Messages

Use `send_messages()` to send one or more messages immediately:

```python
# Send a simple text message
await app.send_messages("Hello, world!")

# Or use TelegramMessage types for more control
from my_bot_framework import TelegramTextMessage, TelegramImageMessage, TelegramDocumentMessage

await app.send_messages(TelegramTextMessage("Formatted <b>message</b>"))
await app.send_messages(TelegramImageMessage("path/to/image.png", caption="My image"))
await app.send_messages(TelegramDocumentMessage("path/to/file.pdf", caption="My document"))

# Send multiple messages at once
await app.send_messages(["Hello", "World"])
await app.send_messages([
    "Check out this image:",
    TelegramImageMessage("path/to/image.png", caption="My image"),
])

# Or send a document
await app.send_messages([
    "Here's the report:",
    TelegramDocumentMessage("path/to/report.pdf", caption="Monthly report"),
])
```

**Automatic Retry:** All message sending automatically retries transient network errors (`TimedOut`, `NetworkError`) up to 3 times with exponential backoff (delays of 1s, 2s, 4s). Rate limiting errors (`RetryAfter`) wait for the duration specified by Telegram before retrying. This ensures reliable message delivery during temporary network issues or rate limits.

### Events

Events run continuously and send messages based on triggers.

#### ActivateOnConditionEvent

Emits messages when a condition becomes truthy:

```python
from my_bot_framework import (
    ActivateOnConditionEvent,
    EditableAttribute,
    Condition,
    MessageBuilder,
)

class DiskFullCondition(Condition):
    def __init__(self) -> None:
        # Use factory method for cleaner syntax
        threshold_attr = EditableAttribute.int("threshold", 90, min_val=0, max_val=100)
        self.editable_attributes = [threshold_attr]
        self._edited = False
    
    def check(self) -> bool:
        return disk_usage() > self.get("threshold")
    
class DiskAlertBuilder(MessageBuilder):
    def __init__(self, condition: DiskFullCondition) -> None:
        self.editable_attributes = []
        self._edited = False
        self._condition = condition
    
    def build(self) -> str:
        threshold = self._condition.get("threshold")
        return f"Disk usage critical (>{threshold}%)!"
    
condition = DiskFullCondition()
builder = DiskAlertBuilder(condition)

event = ActivateOnConditionEvent(
    event_name="disk_alert",
    condition=condition,
    message_builder=builder,
    poll_seconds=60.0,
    fire_when_edited=False,  # Don't fire just because threshold was edited
)
app.register_event(event)

# Edit at runtime (triggers immediate re-check, but only fires if condition is True):
event.edit("condition.threshold", "95")
```

#### TimeEvent

Emits messages at regular intervals (subclass of ActivateOnConditionEvent):

```python
from my_bot_framework import TimeEvent

event = TimeEvent(
    event_name="status_check",
    interval_hours=0.5,  # Every 30 minutes (minimum 5 minutes)
    message_builder=get_status,
    fire_on_first_check=True,  # Emit immediately on start
)
app.register_event(event)

# Edit interval at runtime:
event.interval_hours = 1.0  # Change to 1 hour
```

#### ThresholdEvent

Emits messages when a value crosses a threshold (subclass of ActivateOnConditionEvent):

```python
from my_bot_framework import ThresholdEvent

event = ThresholdEvent(
    event_name="cpu_alert",
    value_getter=lambda: get_cpu_percent(),
    threshold=90.0,
    message_builder=lambda: "CPU usage is high!",
    above=True,  # Fire when value > threshold
    cooldown_seconds=300.0,  # 5 minute cooldown
)
app.register_event(event)

# Edit threshold at runtime:
event.threshold = 80.0
```

#### Event Factories

Factory functions for additional patterns:

```python
from my_bot_framework import create_file_change_event

# File change monitoring
event = create_file_change_event(
    event_name="config_changed",
    file_path="/etc/myapp/config.yaml",
    message_builder=lambda path: f"Config file was modified: {path}",
)
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
- **Inline Keyboard** (attached to message):
  - `InlineKeyboardChoiceDialog` - User selects from inline keyboard options
  - `InlineKeyboardPaginatedChoiceDialog` - User selects from paginated inline keyboard options (shows first page as buttons, remaining items as numbered text list)
  - `InlineKeyboardConfirmDialog` - Yes/No prompt with inline keyboard
- **Reply Keyboard** (buttons at bottom of chat):
  - `ReplyKeyboardChoiceDialog` - User selects from reply keyboard options
  - `ReplyKeyboardPaginatedChoiceDialog` - User selects from paginated reply keyboard options
  - `ReplyKeyboardConfirmDialog` - Yes/No prompt with reply keyboard
- **Other Leaf Dialogs**:
  - `UserInputDialog` - User enters text (with optional validation; prompt may be callable; keyboard auto-removed on text input)
  - `EditEventDialog` - Edit an event's editable attributes via inline keyboard

**Composite Dialogs** (multi-step):
- `SequenceDialog` - Run dialogs in order
- `BranchDialog` - Condition-based branching
- `InlineKeyboardChoiceBranchDialog` - User selects branch via inline keyboard
- `ReplyKeyboardChoiceBranchDialog` - User selects branch via reply keyboard
- `LoopDialog` - Repeat until exit condition
- `DialogHandler` - Wrap dialog with completion callback

```python
from my_bot_framework import (
    InlineKeyboardChoiceDialog, InlineKeyboardPaginatedChoiceDialog,
    InlineKeyboardConfirmDialog, UserInputDialog,
    ReplyKeyboardChoiceDialog, ReplyKeyboardConfirmDialog,
    SequenceDialog, DialogHandler, DialogCommand,
    KeyboardType, create_choice_dialog, create_confirm_dialog,
    CANCELLED, is_cancelled,
)

# Simple inline keyboard choice dialog (default)
color_dialog = ChoiceDialog("Pick a color:", [
    ("Red", "red"),
    ("Green", "green"),
    ("Blue", "blue"),
])

# Reply keyboard choice dialog (buttons at bottom of chat)
color_dialog_reply = ReplyKeyboardChoiceDialog("Pick a color:", [
    ("Red", "red"),
    ("Green", "green"),
    ("Blue", "blue"),
])

# Using factory function with keyboard type
color_dialog_factory = create_choice_dialog(
    prompt="Pick a color:",
    choices=[("Red", "red"), ("Green", "green"), ("Blue", "blue")],
    keyboard_type=KeyboardType.REPLY,  # or KeyboardType.INLINE (default)
)

# Paginated choice dialog (for long lists)
expenses = [
    ("Rent $1200", "1"),
    ("Groceries $95", "2"),
    ("Gas $45", "3"),
    ("Utilities $150", "4"),
    ("Internet $60", "5"),
    ("Phone $80", "6"),
    ("Insurance $200", "7"),
    # ... many more items
]
expense_dialog = PaginatedChoiceDialog(
    prompt="Select expense to remove:",
    items=expenses,
    page_size=5,  # Show first 5 as buttons
    more_label="More...",  # Button label for remaining items
)

# Multi-step sequence with mixed keyboard types
survey_dialog = SequenceDialog([
    ("name", UserInputDialog("What is your name?")),
    ("rating", ChoiceDialog("Rate our service:", [
        ("5 Stars", "5"),
        ("4 Stars", "4"),
        ("3 Stars", "3"),
    ])),
    ("recommend", ReplyKeyboardConfirmDialog("Would you recommend us?")),
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

#### Factory Functions

Factory functions provide a convenient way to create dialogs with a specified keyboard type:

```python
from my_bot_framework import (
    KeyboardType,
    create_choice_dialog,
    create_confirm_dialog,
    create_paginated_choice_dialog,
    create_choice_branch_dialog,
)

# Create choice dialog with reply keyboard
dialog = create_choice_dialog(
    prompt="Select an option:",
    choices=[("Option 1", "opt1"), ("Option 2", "opt2")],
    keyboard_type=KeyboardType.REPLY,
    include_cancel=True,
)

# Create confirmation dialog with inline keyboard (default)
confirm = create_confirm_dialog(
    prompt="Are you sure?",
    keyboard_type=KeyboardType.INLINE,
    yes_label="Yes",
    no_label="No",
    include_cancel=False,
)

# Create paginated choice dialog
paginated = create_paginated_choice_dialog(
    prompt="Select item:",
    items=[("Item 1", "1"), ("Item 2", "2"), ...],
    keyboard_type=KeyboardType.REPLY,
    page_size=5,
    more_label="More...",
    include_cancel=True,
)

# Create choice branch dialog
branch = create_choice_branch_dialog(
    prompt="Select action:",
    branches={
        "edit": ("Edit", edit_dialog),
        "delete": ("Delete", delete_dialog),
    },
    keyboard_type=KeyboardType.INLINE,
    include_cancel=True,
)
```

#### EditEventDialog

Edit any event's editable attributes via an inline keyboard interface:

```python
from my_bot_framework import EditEventDialog, DialogCommand

# Create an event with editable attributes
event = ActivateOnConditionEvent(
    event_name="my_event",
    condition=my_condition,  # Has editable attributes
    message_builder=my_builder,  # Has editable attributes
)

# Simple usage - edit all fields
edit_dialog = EditEventDialog(event)

# With cross-field validation
def validate_limits(context):
    """Ensure limit_min < limit_max."""
    min_val = context.get("condition.limit_min", event.get("condition.limit_min"))
    max_val = context.get("condition.limit_max", event.get("condition.limit_max"))
    if min_val is not None and max_val is not None and min_val >= max_val:
        return False, f"limit_min ({min_val}) must be < limit_max ({max_val})"
    return True, ""

validated_dialog = EditEventDialog(event, validator=validate_limits)

# Register as command
app.register_command(DialogCommand("/edit", "Edit event settings", validated_dialog))
```

The dialog shows a field list with current values. Boolean fields use toggle buttons, other fields use text input. Edits are staged and only applied when clicking Done.

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

#### Validators

The framework provides reusable validation functions for `UserInputDialog`. All validators follow the pattern `(value: str) -> tuple[bool, str]` where the tuple contains `(is_valid, error_message)`.

**Basic Validators:**

```python
from my_bot_framework import (
    UserInputDialog,
    validate_positive_float,
    validate_positive_int,
    validate_non_empty,
)

# Validate positive decimal numbers
price_dialog = UserInputDialog(
    prompt="Enter price:",
    validator=validate_positive_float,
)

# Validate positive integers
age_dialog = UserInputDialog(
    prompt="Enter age:",
    validator=validate_positive_int,
)

# Validate non-empty strings
name_dialog = UserInputDialog(
    prompt="Enter name:",
    validator=validate_non_empty,
)
```

**Factory Validators:**

Factory functions create validators with custom parameters:

```python
from my_bot_framework import (
    validate_int_range,
    validate_float_range,
    validate_date_format,
    validate_regex,
)

# Integer range validation (1-100 inclusive)
age_validator = validate_int_range(1, 100)
age_dialog = UserInputDialog(
    prompt="Enter age (1-100):",
    validator=age_validator,
)

# Float range validation (0.0-1.0 inclusive)
probability_validator = validate_float_range(0.0, 1.0)
prob_dialog = UserInputDialog(
    prompt="Enter probability (0.0-1.0):",
    validator=probability_validator,
)

# Date format validation
date_validator = validate_date_format("%Y-%m-%d", "YYYY-MM-DD")
date_dialog = UserInputDialog(
    prompt="Enter date (YYYY-MM-DD):",
    validator=date_validator,
)

# Regex pattern validation
identifier_validator = validate_regex(
    r"^[a-z_][a-z0-9_]*$",
    "Invalid identifier. Use lowercase letters, numbers, and underscores.",
)
name_dialog = UserInputDialog(
    prompt="Enter identifier:",
    validator=identifier_validator,
)
```

**Custom Validators:**

You can create your own validator functions:

```python
def validate_email(value: str) -> tuple[bool, str]:
    """Validate email format."""
    import re
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if re.match(pattern, value):
        return True, ""
    return False, "Invalid email format."

email_dialog = UserInputDialog(
    prompt="Enter email:",
    validator=validate_email,
)
```

### Message Types

The framework provides several message wrappers:

```python
from my_bot_framework import (
    TelegramTextMessage,
    TelegramImageMessage,
    TelegramDocumentMessage,
    TelegramOptionsMessage,
    TelegramEditMessage,
    TelegramReplyKeyboardMessage,
    TelegramRemoveReplyKeyboardMessage,
)

# Plain text (auto-chunked for long messages)
TelegramTextMessage("Hello, world!")

# Image with caption
TelegramImageMessage("/path/to/image.png", caption="My image")

# Document/file with caption
TelegramDocumentMessage("/path/to/document.pdf", caption="My document")

# Message with inline keyboard
TelegramOptionsMessage("Choose an option:", keyboard_markup)

# Edit existing message
TelegramEditMessage(message_id=123, text="Updated text")

# Message with persistent reply keyboard (buttons at bottom of chat)
TelegramReplyKeyboardMessage(
    text="Select an option:",
    keyboard=[
        ["Option 1", "Option 2"],
        ["Option 3"],
    ],
    resize_keyboard=True,  # Auto-resize buttons to fit
    one_time_keyboard=False,  # Keyboard stays visible after use
)

# Remove the persistent reply keyboard
TelegramRemoveReplyKeyboardMessage("Keyboard removed.")
```

#### HTML Escaping

All messages are sent with `parse_mode=HTML`. If your text contains HTML special characters (`<`, `>`, `&`) that should be displayed literally (not parsed as HTML), you must escape them using `html.escape()`:

```python
import html
from my_bot_framework import TelegramTextMessage, InvalidHtmlError

# Text with HTML special characters - MUST escape
user_input = "Use <script> tags for JavaScript"
safe_text = html.escape(user_input)  # "Use &lt;script&gt; tags for JavaScript"
message = TelegramTextMessage(safe_text)

# If you forget to escape, InvalidHtmlError is raised (fatal - terminates the bot)
try:
    message = TelegramTextMessage("Invalid <unclosed tag")
    await app.send_messages(message)
except InvalidHtmlError as e:
    print(f"HTML error: {e}")
    # Fix: html.escape() your text
```

**Important:** `InvalidHtmlError` is a **fatal error** that propagates up and terminates the bot. This ensures developers notice and fix HTML escaping issues during development. The exception provides:
- The original Telegram API error
- The offending text (truncated for display)
- Clear instructions to use `html.escape()`

## Group Chat Setup

When running a bot in Telegram group chats (as opposed to private chats), you may need to configure Group Privacy Mode for full functionality.

### Default Behavior

By default, Telegram's **Group Privacy Mode** is **enabled** for all bots. In this mode, bots only receive:
- Messages starting with `/` (commands)
- Replies to the bot's own messages
- Messages that @mention the bot by username
- Service messages (users joining/leaving, etc.)

### Why This Matters

Group Privacy Mode can cause issues with dialogs that expect free-form text input (like `UserInputDialog`). If a user types a response without replying to the bot's prompt message, the bot never receives it — the message silently doesn't arrive.

**What works with privacy mode enabled:**
- All commands (`/start`, `/settings`, etc.)
- Reply keyboard buttons (sent as replies to the bot's keyboard message)
- Inline keyboard buttons (use callback queries, not text messages)

**What fails silently:**
- `UserInputDialog` prompts like "Enter a description:" — if the user types their response without explicitly replying to the prompt message, the bot won't see it

### Disabling Group Privacy Mode

To allow your bot to receive **all messages** in group chats (required for text input dialogs):

1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/setprivacy`
3. Select your bot
4. Choose **Disable**

After disabling privacy mode, your bot will receive all messages in group chats, and `UserInputDialog` will work correctly.

> **Note:** This setting only affects group chats. In private (one-on-one) chats, bots always receive all messages regardless of this setting.

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

## Editable Attributes

Runtime-editable parameters with validation. The `EditableAttribute` class provides factory methods for common types, making it easy to create validated attributes:

```python
from my_bot_framework import EditableAttribute

# Factory methods for common types (recommended)
threshold = EditableAttribute.int("threshold", 90, min_val=0, max_val=100)
rate = EditableAttribute.float("rate", 1.0, positive=True)
enabled = EditableAttribute.bool("enabled", True)
mode = EditableAttribute.str("mode", "auto", choices=["auto", "manual"])

# Optional types (allow None)
limit = EditableAttribute.float("limit", None, optional=True, positive=True)
max_count = EditableAttribute.int("max_count", None, optional=True, min_val=1)
prefix = EditableAttribute.str("prefix", None, optional=True, choices=["A", "B", "C"])

# Update via string input (parsed and validated)
threshold.value = "95"  # Parsed as int, validated against min/max
rate.value = "2.5"      # Parsed as float, validated as positive
enabled.value = "yes"   # Parses common boolean strings (true/false, yes/no, 1/0, on/off)

# Or set directly (still validated)
threshold.value = 80
rate.value = 3.0
enabled.value = False
```

### Factory Methods

The `EditableAttribute` class provides convenient factory methods:

- **`EditableAttribute.float(name, initial_value, *, positive=False, min_val=None, max_val=None, optional=False)`** - Float with optional constraints. Set `optional=True` to allow None values.
- **`EditableAttribute.int(name, initial_value, *, positive=False, min_val=None, max_val=None, optional=False)`** - Integer with optional constraints. Set `optional=True` to allow None values.
- **`EditableAttribute.bool(name, initial_value, *, optional=False)`** - Boolean (parses true/false, yes/no, 1/0, on/off). Set `optional=True` to allow None values.
- **`EditableAttribute.str(name, initial_value, *, choices=None, optional=False)`** - String with optional choices validation. Set `optional=True` to allow None values.

### Advanced Usage

For custom validation or parsing, use the full constructor:

```python
field = EditableAttribute(
    name="threshold",
    field_type=int,
    initial_value=100,
    parse=int,  # String parser
    validator=lambda v: (v > 0, "Must be positive"),
)
```

## Utilities

### Message Chunking

Long messages are automatically chunked to fit Telegram's message limit:

```python
from my_bot_framework import divide_message_to_chunks

chunks = divide_message_to_chunks(long_text, chunk_size=4000)
```

### List Formatting

Format lists for Telegram messages with automatic HTML escaping:

```python
from my_bot_framework import (
    format_numbered_list,
    format_bullet_list,
    format_key_value_pairs,
)

# Numbered list (default starts at 1)
items = ["First item", "Second item", "Third item"]
numbered = format_numbered_list(items)
# Returns: "1. First item\n2. Second item\n3. Third item"

# Custom starting number
numbered = format_numbered_list(items, start=5)
# Returns: "5. First item\n6. Second item\n7. Third item"

# Bullet list (default uses "•")
bulleted = format_bullet_list(items)
# Returns: "• First item\n• Second item\n• Third item"

# Custom bullet character
bulleted = format_bullet_list(items, bullet="-")
# Returns: "- First item\n- Second item\n- Third item"

# Key-value pairs (default separator is ": ")
pairs = [("Name", "John"), ("Age", "30"), ("City", "New York")]
kv_pairs = format_key_value_pairs(pairs)
# Returns: "Name: John\nAge: 30\nCity: New York"

# Custom separator
kv_pairs = format_key_value_pairs(pairs, separator=" = ")
# Returns: "Name = John\nAge = 30\nCity = New York"
```

**Note:** All three functions automatically escape HTML special characters (`<`, `>`, `&`) in the input strings, making them safe for use with Telegram's HTML parse mode. Empty lists return an empty string.

## License

MIT
