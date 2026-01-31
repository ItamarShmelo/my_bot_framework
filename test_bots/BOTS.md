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

## Adding New Test Bots

When adding a new test bot:

1. Create a new `.py` file in this directory
2. Use `get_credentials()` pattern for environment variables
3. Document what framework features it tests
4. Update this file with the new bot's documentation
