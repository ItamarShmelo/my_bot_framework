# Test Bots

This directory contains test bots that validate the functionality of the bot framework.

## Setup

All bots read credentials from files in the `test_bots` directory:

1. Create a `.token` file containing your Telegram bot token
2. Create a `.chat_id` file containing your Telegram chat ID

```bash
echo "your_bot_token" > test_bots/.token
echo "your_chat_id" > test_bots/.chat_id
```

**Note:** These files are gitignored to prevent accidental commits of credentials.

## Available Bots

### basic_bot.py

**Purpose:** Tests core framework functionality.

**Features tested:**
- `BotApplication` initialization and lifecycle
- `TimeEvent` with `fire_on_first_check`
- `SimpleCommand` registration
- Built-in `/terminate` and `/commands`

**Commands:**
| Command | Description |
|---------|-------------|
| `/hello` | Returns a greeting message |
| `/status` | Shows bot status |
| `/info` | Shows what this bot tests |
| `/commands` | Lists all commands (built-in) |
| `/terminate` | Shuts down the bot (built-in) |

**Events:**
- Heartbeat every 5 minutes

**Run:**
```bash
python test_bots/basic_bot.py
```

---

### condition_bot.py

**Purpose:** Tests condition-based events and editable parameters.

**Features tested:**
- `ActivateOnConditionEvent` with polling
- `EditableAttribute` for runtime parameter changes
- Condition/MessageBuilder interfaces

**Commands:**
| Command | Description |
|---------|-------------|
| `/sensor` | Shows current simulated sensor value |
| `/threshold` | Shows current alert threshold |
| `/info` | Shows what this bot tests |

**Events:**
- Sensor alert when value exceeds threshold (polls every 10 seconds)

**Run:**
```bash
python test_bots/condition_bot.py
```

---

### dialog_bot.py

**Purpose:** Tests the Dialog Composite system.

**Features tested:**
- `InlineKeyboardChoiceDialog` - Inline keyboard selection with static and dynamic choices
- `UserInputDialog` - Text input with optional validation
- `InlineKeyboardConfirmDialog` - Yes/No prompts with inline keyboard
- `SequenceDialog` - Sequential dialogs with named values
- `BranchDialog` - Condition-based branching
- `InlineKeyboardChoiceBranchDialog` - Inline keyboard-driven branching
- `LoopDialog` - Repeat until exit condition (with exit_value and exit_condition)
- Shared context across all dialogs
- Dynamic choices via callable functions

**Commands:**
| Command | Description |
|---------|-------------|
| `/simple` | SequenceDialog: name + mood selection |
| `/confirm` | InlineKeyboardConfirmDialog with custom labels |
| `/validated` | UserInputDialog with validation (1-100) |
| `/dynamic` | Dynamic choices based on previous selection |
| `/branch` | InlineKeyboardChoiceBranchDialog (quick vs full setup) |
| `/condition` | BranchDialog with age-based condition |
| `/loop` | LoopDialog until 'done' entered |
| `/loopvalid` | LoopDialog until valid email (max 5) |
| `/full` | Complete onboarding: all dialog types |
| `/info` | Shows what this bot tests |

**Dialog Types Tested:**

| Dialog Type | Description |
|-------------|-------------|
| `InlineKeyboardChoiceDialog` | Static/dynamic inline keyboard options |
| `UserInputDialog` | Text input with validator |
| `InlineKeyboardConfirmDialog` | Yes/No with custom labels |
| `SequenceDialog` | Named dialogs in sequence |
| `BranchDialog` | Condition function branching |
| `InlineKeyboardChoiceBranchDialog` | User-driven branching |
| `LoopDialog` | Exit by value/condition/max |

**Run:**
```bash
python test_bots/dialog_bot.py
```

---

### dialog_handler_bot.py

**Purpose:** Tests the DialogHandler and cancellation features.

**Features tested:**
- `DialogHandler` - Wrap dialogs with on_complete callback
- `CANCELLED` sentinel - Unambiguous cancellation detection
- `is_cancelled()` - Helper function for checking cancellation
- Nested `DialogHandler` - Multiple handlers in a chain
- `DialogResult` - Standardized result structure from `build_result()`
- Async `on_complete` callbacks
- Integration with `InlineKeyboardChoiceDialog` and `InlineKeyboardConfirmDialog`
- Integration with `SequenceDialog`

**Commands:**
| Command | Description |
|---------|-------------|
| `/handler` | Basic DialogHandler with on_complete callback |
| `/sequence_handler` | DialogHandler wrapping SequenceDialog |
| `/async_handler` | DialogHandler with async on_complete callback |
| `/nested_handler` | Nested DialogHandlers |
| `/cancel_test` | Cancellation handling with CANCELLED sentinel |
| `/info` | Shows what this bot tests |

**Features Demonstrated:**

| Feature | Description |
|---------|-------------|
| `DialogHandler` | Composite that runs a dialog and calls on_complete |
| `CANCELLED` | Sentinel object for unambiguous cancellation |
| `is_cancelled()` | Helper to check if result is CANCELLED |
| `build_result()` | Polymorphic method for standardized results |

**Run:**
```bash
python test_bots/dialog_handler_bot.py
```

---

### editable_bot.py

**Purpose:** Tests runtime-editable parameters via dialogs.

**Features tested:**
- `EditableAttribute` factory methods (`int()`, `str()` with choices, `optional=True`)
- `EditableMixin` - The `edited` flag for immediate re-check
- `DialogCommand` with `DialogHandler` for editing
- Condition/MessageBuilder edit routing
- `ActivateOnConditionEvent` with editable parameters

**Commands:**
| Command | Description |
|---------|-------------|
| `/sensor` | Show current simulated sensor value |
| `/settings` | Show current threshold and alert level |
| `/edit_threshold` | Edit threshold via UserInputDialog |
| `/edit_level` | Edit alert level via InlineKeyboardChoiceDialog |
| `/edit_all` | Edit all settings via SequenceDialog |
| `/info` | Shows what this bot tests |

**Events:**
- Sensor alert when value exceeds editable threshold (polls every 15 seconds)

**Editable Fields:**
| Field | Type | Range | Default |
|-------|------|-------|---------|
| `threshold` | int | 0-100 | 80 |
| `alert_level` | str | info/warning/critical | warning |
| `max_alerts` | int (optional) | ≥1 or None | None (unlimited) |

**Run:**
```bash
python test_bots/editable_bot.py
```

---

### threshold_bot.py

**Purpose:** Tests the ThresholdEvent class for value monitoring.

**Features tested:**
- `ThresholdEvent` class (subclass of ActivateOnConditionEvent)
- `threshold` property for runtime editing
- Cooldown mechanism to prevent spam
- Above/below threshold detection

**Commands:**
| Command | Description |
|---------|-------------|
| `/status` | Show current CPU and memory values |
| `/thresholds` | Show current threshold settings |
| `/edit_cpu` | Edit CPU threshold via dialog |
| `/edit_memory` | Edit memory threshold via dialog |
| `/info` | Shows what this bot tests |

**Events:**
- CPU alert when value > 80% (polls every 5s, 30s cooldown)
- Memory alert when value > 75% (polls every 5s, 30s cooldown)

**Run:**
```bash
python test_bots/threshold_bot.py
```

---

### file_watcher_bot.py

**Purpose:** Tests the create_file_change_event factory.

**Features tested:**
- `create_file_change_event` factory function
- File modification time monitoring
- Editable `file_path` field

**Commands:**
| Command | Description |
|---------|-------------|
| `/file` | Show monitored file path |
| `/touch` | Touch file to trigger change detection |
| `/contents` | Show file contents |
| `/info` | Shows what this bot tests |

**Events:**
- File change alert when monitored file is modified (polls every 5s)

**Run:**
```bash
python test_bots/file_watcher_bot.py
```

---

### edit_event_dialog_bot.py

**Purpose:** Tests the EditEventDialog class for editing event attributes via inline keyboard.

**Features tested:**
- `EditEventDialog` - Edit event attributes via inline keyboard
- Boolean fields with True/False toggle buttons
- Numeric fields with text input
- Cross-field validation (`limit_min < limit_max`)
- Staged edits applied only on Done button
- Manual cross-field validation pattern (closures + context)

**Commands:**
| Command | Description |
|---------|-------------|
| `/sensor` | Show current simulated sensor value |
| `/settings` | Show current limit_min, limit_max, log_scale |
| `/edit` | Edit settings with EditEventDialog (cross-field validation) |
| `/manual_edit` | Edit limits using closure pattern (educational) |
| `/info` | Shows what this bot tests |

**Events:**
- Range alert when sensor value is outside limit_min/limit_max (polls every 30s)

**Editable Fields:**
| Field | Type | Range | Default |
|-------|------|-------|---------|
| `condition.limit_min` | float | 0-100 | 20.0 |
| `condition.limit_max` | float | 0-100 | 80.0 |
| `condition.log_scale` | bool | True/False | False |

**Cross-Field Validation:**
The `/edit` command uses `EditEventDialog` with a validator that ensures `limit_min < limit_max`. If validation fails, the user must fix the value or cancel the field edit.

**Educational Pattern:**
The `/manual_edit` command demonstrates how to achieve similar cross-field validation without `EditEventDialog`, using:
- Closures to capture shared state
- Dialog context to pass values between sequential dialogs
- UserInputDialog validators that reference external state

**Run:**
```bash
python test_bots/edit_event_dialog_bot.py
```

---

### document_bot.py

**Purpose:** Tests the TelegramDocumentMessage class for sending files.

**Features tested:**
- `TelegramDocumentMessage` - Sending document files via Telegram
- Caption support (plain text and HTML)
- Path types (both `str` and `Path` objects)
- Error handling for missing files

**Commands:**
| Command | Description |
|---------|-------------|
| `/doc` | Send a document without caption |
| `/doc_caption` | Send a document with plain caption |
| `/doc_html` | Send a document with HTML-formatted caption |
| `/doc_string` | Send document using string path |
| `/doc_error` | Test error handling (missing file) |
| `/info` | Shows what this bot tests |
| `/commands` | Lists all commands (built-in) |
| `/terminate` | Shuts down the bot (built-in) |

**Run:**
```bash
python test_bots/document_bot.py
```

---

### paginated_dialog_bot.py

**Purpose:** Tests the InlineKeyboardPaginatedChoiceDialog class for displaying long lists with pagination.

**Features tested:**
- `InlineKeyboardPaginatedChoiceDialog` - Paginated inline keyboard selection
- Static items list
- Dynamic items via callable
- Different page sizes (3, 4, 5 items per page)
- "More..." button behavior (only shown when items exceed page_size)
- Text input selection for remaining items (numbered list)
- Cancel functionality (with and without cancel button)
- Integration with `DialogHandler` for result processing

**Commands:**
| Command | Description |
|---------|-------------|
| `/info` | Shows what this bot tests |
| `/start` | Show available commands |
| `/short` | Test short list (no More button) |
| `/expenses` | Test expense list with pagination (5 items/page) |
| `/countries` | Test country list with small page size (3 items/page) |
| `/tasks` | Test dynamic items via callable |
| `/nocancel` | Test without cancel button |
| `/commands` | Lists all commands (built-in) |
| `/terminate` | Shuts down the bot (built-in) |

**Test Scenarios:**

| Scenario | Page Size | Items | Has "More..." |
|----------|-----------|-------|---------------|
| `/short` | 5 | 3 fruits | No |
| `/expenses` | 5 | 12 expenses | Yes |
| `/countries` | 3 | 20 countries | Yes |
| `/tasks` | 4 | 8 dynamic tasks | Yes |
| `/nocancel` | 3 | 8 expenses | Yes |

**Run:**
```bash
python test_bots/paginated_dialog_bot.py
```

---

### utilities_bot.py

**Purpose:** Tests formatting utilities and validation functions.

**Features tested:**
- `format_numbered_list` - Format items as numbered list with custom start
- `format_bullet_list` - Format items as bullet list with custom bullet character
- `format_key_value_pairs` - Format key-value pairs with custom separator
- `divide_message_to_chunks` - Split messages into fixed-size chunks
- `validate_positive_int` - Validate positive integers
- `validate_positive_float` - Validate positive floats
- `validate_int_range` - Validate integers within a range (factory function)
- `validate_float_range` - Validate floats within a range (factory function)
- `validate_date_format` - Validate date strings matching a format (factory function)
- `validate_regex` - Validate strings matching a regex pattern (factory function)
- Integration with `UserInputDialog` and `DialogHandler` for interactive validation

**Commands:**
| Command | Description |
|---------|-------------|
| `/info` | Shows what this bot tests |
| `/numbered` | Demonstrates format_numbered_list with examples |
| `/bullet` | Demonstrates format_bullet_list with examples |
| `/keyvalue` | Demonstrates format_key_value_pairs with examples |
| `/chunks` | Demonstrates divide_message_to_chunks with examples |
| `/validate_int` | Test validate_positive_int on user input |
| `/validate_float` | Test validate_positive_float on user input |
| `/validate_range` | Test validate_int_range(1, 100) on user input |
| `/validate_float_range` | Test validate_float_range(0.0, 1.0) on user input |
| `/validate_date` | Test validate_date_format("%Y-%m-%d") on user input |
| `/validate_email` | Test validate_regex with email pattern on user input |

**Run:**
```bash
python test_bots/utilities_bot.py
```

---

### reply_keyboard_bot.py

**Purpose:** Tests the TelegramReplyKeyboardMessage and TelegramRemoveReplyKeyboardMessage classes.

**Features tested:**
- `TelegramReplyKeyboardMessage` - Sending messages with persistent reply keyboards
- `TelegramRemoveReplyKeyboardMessage` - Removing persistent reply keyboards
- Keyboard layouts (2x2, single row, single column)
- `resize_keyboard` parameter (resized vs full-size buttons)
- `one_time_keyboard` parameter (keyboard hides after use)
- Combined parameters (one_time_keyboard + resize_keyboard together)
- HTML formatting in message text
- Custom removal messages with HTML formatting

**Commands:**
| Command | Description |
|---------|-------------|
| `/info` | Shows what this bot tests |
| `/keyboard` | Show a simple 2x2 reply keyboard |
| `/row` | Show a single row reply keyboard |
| `/column` | Show a single column reply keyboard |
| `/onetime` | Show a one-time keyboard (hides after use) |
| `/noresize` | Show keyboard without resize (tall buttons) |
| `/html` | Show keyboard with HTML-formatted text |
| `/combined` | Show keyboard with combined parameters (one-time + no-resize) |
| `/remove` | Remove the reply keyboard |
| `/remove_custom` | Remove keyboard with custom HTML message |
| `/commands` | Lists all commands (built-in) |
| `/terminate` | Shuts down the bot (built-in) |

**Run:**
```bash
python test_bots/reply_keyboard_bot.py
```

---

### reply_keyboard_dialog_bot.py

**Purpose:** Tests the reply keyboard dialog classes that use Telegram's reply keyboard instead of inline keyboard.

**Features tested:**
- `ReplyKeyboardChoiceDialog` - Choice dialog using reply keyboard
- `ReplyKeyboardConfirmDialog` - Confirm dialog using reply keyboard (with and without cancel)
- `ReplyKeyboardPaginatedChoiceDialog` - Paginated choice dialog using reply keyboard
- `ReplyKeyboardChoiceBranchDialog` - Choice branch dialog using reply keyboard
- Factory functions with `keyboard_type=KeyboardType.REPLY`:
  - `create_choice_dialog()` with `KeyboardType.REPLY`
  - `create_confirm_dialog()` with `KeyboardType.REPLY`
  - `create_paginated_choice_dialog()` with `KeyboardType.REPLY`
  - `create_choice_branch_dialog()` with `KeyboardType.REPLY`
- Text matching for button labels (reply keyboards send text messages)
- Cancel functionality (with `include_cancel` parameter)
- Dynamic choices via callable functions
- Integration with `DialogHandler` and `SequenceDialog`
- Custom yes/no labels for confirm dialogs

**Commands:**
| Command | Description |
|---------|-------------|
| `/info` | Shows what this bot tests |
| `/choice` | Test ReplyKeyboardChoiceDialog (direct class) |
| `/choice_factory` | Test create_choice_dialog with KeyboardType.REPLY |
| `/confirm` | Test ReplyKeyboardConfirmDialog (direct class) |
| `/confirm_cancel` | Test ReplyKeyboardConfirmDialog with cancel button |
| `/confirm_factory` | Test create_confirm_dialog with KeyboardType.REPLY |
| `/paginated` | Test ReplyKeyboardPaginatedChoiceDialog (direct class) |
| `/paginated_factory` | Test create_paginated_choice_dialog with KeyboardType.REPLY |
| `/dynamic_choice` | Test dynamic choices via callable |
| `/branch` | Test ReplyKeyboardChoiceBranchDialog (direct class) |
| `/branch_factory` | Test create_choice_branch_dialog with KeyboardType.REPLY |
| `/choice_handler` | Test ReplyKeyboardChoiceDialog with DialogHandler |
| `/confirm_handler` | Test ReplyKeyboardConfirmDialog with DialogHandler |

**Dialog Types Tested:**

| Dialog Type | Description |
|-------------|-------------|
| `ReplyKeyboardChoiceDialog` | Static/dynamic keyboard options using reply keyboard |
| `ReplyKeyboardConfirmDialog` | Yes/No with custom labels using reply keyboard |
| `ReplyKeyboardPaginatedChoiceDialog` | Paginated options with "More..." button using reply keyboard |
| `ReplyKeyboardChoiceBranchDialog` | User-driven branching using reply keyboard |

**Run:**
```bash
python test_bots/reply_keyboard_dialog_bot.py
```

---

### bad_html_bot.py

**Purpose:** Tests InvalidHtmlError handling and fatal error propagation.

**Features tested:**
- `InvalidHtmlError` is raised when sending unescaped HTML
- Fatal error propagates up and terminates the bot
- CRITICAL-level log with full traceback is produced

**Commands:**
| Command | Description |
|---------|-------------|
| `/info` | Shows what this bot tests |
| `/bad_html` | Send a message with invalid HTML (triggers fatal InvalidHtmlError) |

**Usage:**
Start the bot and send `/bad_html`. The bot will attempt to send a message containing raw '<' and '>' characters, which Telegram cannot parse as HTML. This triggers `InvalidHtmlError`, which propagates up and terminates the bot with a CRITICAL log and full traceback.

**Run:**
```bash
python test_bots/bad_html_bot.py
```

---

### network_error_bot.py

**Purpose:** Tests exception safety of the polling layer by monkey-patching `bot.get_updates` to inject intermittent failures.

**Features tested:**
- Exception handling in `poll_updates()` for `TimedOut` errors
- Exception handling in `poll_updates()` for `NetworkError` errors
- `UpdatePollerMixin.poll()` safety net for unexpected errors (e.g., `RuntimeError`)
- Normal polling resumption after transient failures
- Monkey-patching pattern for testing error scenarios

**Commands:**
| Command | Description |
|---------|-------------|
| `/stats` | Show error injection statistics (poll cycles, injected error counts) |
| `/hello` | Say hello (proves bot is responsive despite errors) |
| `/info` | Show what this bot tests |
| `/commands` | Lists all commands (built-in) |
| `/terminate` | Shuts down the bot (built-in) |

**Events:**
- Heartbeat every 5 minutes (proves bot continues running despite errors)

**Error Injection Schedule:**
- Every 3rd poll cycle: `TimedOut` error
- Every 5th poll cycle: `NetworkError` error
- Every 11th poll cycle: `RuntimeError` (unexpected error)

**Usage:**
The bot automatically injects errors on a fixed schedule. Use `/stats` to see how many errors have been injected and verify the bot continues running normally. The bot should handle all injected errors gracefully and continue polling.

**Run:**
```bash
python test_bots/network_error_bot.py
```

---

## Adding New Test Bots

When adding a new test bot:

1. Create a new `.py` file in this directory
2. Use `get_credentials()` pattern for reading `.token` and `.chat_id` files
3. Document what framework features it tests
4. Update this file with the new bot's documentation
