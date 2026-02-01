# Test Bots

This directory contains test bots that validate the functionality of the bot framework.

## Setup

All bots read credentials from environment variables:

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

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
- `EditableField` for runtime parameter changes
- Condition function with kwargs

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
- `EditableField` - Type parsing and validation
- `EditableMixin` - The `edited` flag for immediate re-check
- `DialogCommand` with `DialogHandler` for editing
- Dynamic kwargs from editable fields to message builders
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

**Run:**
```bash
python test_bots/editable_bot.py
```

---

## Adding New Test Bots

When adding a new test bot:

1. Create a new `.py` file in this directory
2. Use `get_credentials()` pattern for environment variables
3. Document what framework features it tests
4. Update this file with the new bot's documentation
