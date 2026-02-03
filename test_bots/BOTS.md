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

**Purpose:** Tests the new Dialog Composite system.

**Features tested:**
- `ChoiceDialog` - Keyboard selection with static and dynamic choices
- `UserInputDialog` - Text input with optional validation
- `ConfirmDialog` - Yes/No prompts
- `SequenceDialog` - Sequential dialogs with named values
- `BranchDialog` - Condition-based branching
- `ChoiceBranchDialog` - Keyboard-driven branching
- `LoopDialog` - Repeat until exit condition
- Shared context across all dialogs

**Commands:**
| Command | Description |
|---------|-------------|
| `/simple` | SequenceDialog: name + mood selection |
| `/confirm` | ConfirmDialog with custom labels |
| `/validated` | UserInputDialog with validation (1-100) |
| `/dynamic` | Dynamic choices based on previous selection |
| `/branch` | ChoiceBranchDialog (quick vs full setup) |
| `/condition` | BranchDialog with age-based condition |
| `/loop` | LoopDialog until 'done' entered |
| `/loopvalid` | LoopDialog until valid email (max 5) |
| `/full` | Complete onboarding: all dialog types |
| `/info` | Shows what this bot tests |

**Dialog Types Tested:**

| Dialog Type | Description |
|-------------|-------------|
| `ChoiceDialog` | Static/dynamic keyboard options |
| `UserInputDialog` | Text input with validator |
| `ConfirmDialog` | Yes/No with custom labels |
| `SequenceDialog` | Named dialogs in sequence |
| `BranchDialog` | Condition function branching |
| `ChoiceBranchDialog` | User-driven branching |
| `LoopDialog` | Exit by value/condition/max |

**Run:**
```bash
python test_bots/dialog_bot.py
```

---

### dialog_handler_bot.py

**Purpose:** Tests the new DialogHandler and cancellation features.

**Features tested:**
- `DialogHandler` - Wrap dialogs with on_complete callback
- `CANCELLED` sentinel - Unambiguous cancellation detection
- `is_cancelled()` - Helper function for checking cancellation
- Nested `DialogHandler` - Multiple handlers in a chain
- `DialogResult` - Standardized result structure
- Async `on_complete` callbacks

**Commands:**
| Command | Description |
|---------|-------------|
| `/handler` | Basic DialogHandler with on_complete callback |
| `/sequence_handler` | DialogHandler wrapping SequenceDialog |
| `/async_handler` | DialogHandler with async on_complete callback |
| `/nested_handler` | Nested DialogHandlers |
| `/cancel_test` | Cancellation handling with CANCELLED sentinel |

**New Features Demonstrated:**

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
| `/edit_level` | Edit alert level via ChoiceDialog |
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

## Adding New Test Bots

When adding a new test bot:

1. Create a new `.py` file in this directory
2. Use `get_credentials()` pattern for reading `.token` and `.chat_id` files
3. Document what framework features it tests
4. Update this file with the new bot's documentation
