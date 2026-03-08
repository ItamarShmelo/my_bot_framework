"""Reply keyboard dialog bot testing merged dialog classes with keyboard_type=REPLY.

Tests:
- ChoiceDialog (keyboard_type=KeyboardType.REPLY) - Choice dialog using reply keyboard
- ConfirmDialog (keyboard_type=KeyboardType.REPLY) - Confirm dialog using reply keyboard
- PaginatedChoiceDialog (keyboard_type=KeyboardType.REPLY) - Paginated choice dialog using reply keyboard
- ChoiceBranchDialog (keyboard_type=KeyboardType.REPLY) - Choice branch dialog using reply keyboard (static + dynamic branches)
- Factory functions with keyboard_type=KeyboardType.REPLY
- Text matching for button labels
- Cancel functionality
- Dynamic choices via callable
"""

from __future__ import annotations

import asyncio
import logging
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
    ChoiceDialog,
    ConfirmDialog,
    PaginatedChoiceDialog,
    ChoiceBranchDialog,
    KeyboardType,
    create_choice_dialog,
    create_confirm_dialog,
    create_paginated_choice_dialog,
    create_choice_branch_dialog,
    UserInputDialog,
    SequenceDialog,
    is_cancelled,
)


def get_credentials() -> tuple[str, str]:
    """Get bot credentials from .token and .chat_id files in test_bots directory."""
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


# =============================================================================
# DIALOG DEFINITIONS
# =============================================================================

# /choice - Tests ChoiceDialog with keyboard_type=REPLY (direct class)
choice_dialog = ChoiceDialog(
    prompt="Choose your favorite color:",
    choices=[
        ("Red", "red"),
        ("Green", "green"),
        ("Blue", "blue"),
        ("Yellow", "yellow"),
    ],
    include_cancel=True,
    keyboard_type=KeyboardType.REPLY,
)


# /choice_factory - Tests create_choice_dialog with KeyboardType.REPLY
choice_factory_dialog = create_choice_dialog(
    prompt="Select a programming language:",
    choices=[
        ("Python", "python"),
        ("JavaScript", "javascript"),
        ("Rust", "rust"),
        ("Go", "go"),
    ],
    keyboard_type=KeyboardType.REPLY,
    include_cancel=True,
)


# /confirm - Tests ConfirmDialog with keyboard_type=REPLY (direct class)
confirm_dialog = ConfirmDialog(
    prompt="Do you want to proceed?",
    yes_label="Yes",
    no_label="No",
    include_cancel=False,
    keyboard_type=KeyboardType.REPLY,
)


# /confirm_cancel - Tests ConfirmDialog with cancel button
confirm_cancel_dialog = ConfirmDialog(
    prompt="Are you sure you want to delete this?",
    yes_label="Yes, delete",
    no_label="No, keep it",
    include_cancel=True,
    keyboard_type=KeyboardType.REPLY,
)


# /confirm_factory - Tests create_confirm_dialog with KeyboardType.REPLY
confirm_factory_dialog = create_confirm_dialog(
    prompt="Continue with the operation?",
    keyboard_type=KeyboardType.REPLY,
    yes_label="Continue",
    no_label="Stop",
    include_cancel=True,
)


# /paginated - Tests PaginatedChoiceDialog with keyboard_type=REPLY (direct class)
paginated_dialog = PaginatedChoiceDialog(
    prompt="Select an expense category:",
    items=[
        ("Rent", "rent"),
        ("Groceries", "groceries"),
        ("Transportation", "transportation"),
        ("Entertainment", "entertainment"),
        ("Utilities", "utilities"),
        ("Healthcare", "healthcare"),
        ("Education", "education"),
        ("Other", "other"),
    ],
    page_size=3,
    include_cancel=True,
    keyboard_type=KeyboardType.REPLY,
)


# /paginated_factory - Tests create_paginated_choice_dialog with KeyboardType.REPLY
paginated_factory_dialog = create_paginated_choice_dialog(
    prompt="Choose a country:",
    items=[
        ("United States", "us"),
        ("United Kingdom", "uk"),
        ("Canada", "ca"),
        ("Australia", "au"),
        ("Germany", "de"),
        ("France", "fr"),
        ("Japan", "jp"),
        ("Brazil", "br"),
        ("India", "in"),
        ("China", "cn"),
    ],
    keyboard_type=KeyboardType.REPLY,
    page_size=4,
    include_cancel=True,
)


# /dynamic_choice - Tests dynamic choices via callable
def get_dynamic_choices(context: dict[str, str]) -> list[tuple[str, str]]:
    """Get choices based on context."""
    category = context.get("category", "general")
    if category == "food":
        return [
            ("Pizza", "pizza"),
            ("Burger", "burger"),
            ("Sushi", "sushi"),
            ("Pasta", "pasta"),
        ]
    elif category == "drink":
        return [
            ("Coffee", "coffee"),
            ("Tea", "tea"),
            ("Juice", "juice"),
            ("Water", "water"),
        ]
    else:
        return [
            ("Option A", "a"),
            ("Option B", "b"),
            ("Option C", "c"),
        ]


dynamic_choice_dialog = SequenceDialog([
    ("category", ChoiceDialog(
        prompt="Select a category:",
        choices=[
            ("Food", "food"),
            ("Drink", "drink"),
            ("Other", "other"),
        ],
        include_cancel=True,
        keyboard_type=KeyboardType.REPLY,
    )),
    ("item", ChoiceDialog(
        prompt="Now select an item:",
        choices=get_dynamic_choices,
        include_cancel=True,
        keyboard_type=KeyboardType.REPLY,
    )),
])


# /branch - Tests ChoiceBranchDialog with keyboard_type=REPLY (direct class)
branch_dialog = ChoiceBranchDialog(
    prompt="Choose a setup option:",
    branches={
        "quick": ("Quick Setup", UserInputDialog("Enter your name:")),
        "full": ("Full Setup", SequenceDialog([
            ("name", UserInputDialog("Enter your name:")),
            ("email", UserInputDialog("Enter your email:")),
        ])),
    },
    include_cancel=True,
    keyboard_type=KeyboardType.REPLY,
)


# /branch_factory - Tests create_choice_branch_dialog with KeyboardType.REPLY
branch_factory_dialog = create_choice_branch_dialog(
    prompt="Select a task:",
    branches={
        "view": ("View Settings", UserInputDialog("Enter setting name:")),
        "edit": ("Edit Settings", SequenceDialog([
            ("key", UserInputDialog("Enter setting key:")),
            ("value", UserInputDialog("Enter setting value:")),
        ])),
    },
    keyboard_type=KeyboardType.REPLY,
    include_cancel=True,
)


# /dynamic_branch - Tests ChoiceBranchDialog with dynamic callable branches (reply keyboard)
def get_dynamic_branches(context: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    """Get branches based on context - branches vary by user_type selection."""
    user_type = context.get("user_type", "basic")
    if user_type == "developer":
        return {
            "quick": ("Quick (name only)", UserInputDialog("Enter your name:")),
            "full": ("Full (name + email)", SequenceDialog([
                ("name", UserInputDialog("Enter your name:")),
                ("email", UserInputDialog("Enter your email:")),
            ])),
        }
    elif user_type == "designer":
        return {
            "portfolio": ("Portfolio setup", UserInputDialog("Enter portfolio URL:")),
            "skills": ("Skills setup", UserInputDialog("List your design tools:")),
        }
    else:
        return {
            "simple": ("Simple", UserInputDialog("Enter your name:")),
        }


dynamic_branch_dialog = SequenceDialog([
    ("user_type", ChoiceDialog(
        prompt="Select your role:",
        choices=[
            ("Developer", "developer"),
            ("Designer", "designer"),
            ("Other", "other"),
        ],
        include_cancel=True,
        keyboard_type=KeyboardType.REPLY,
    )),
    ("branch_result", ChoiceBranchDialog(
        prompt="Select setup path:",
        branches=get_dynamic_branches,
        include_cancel=True,
        keyboard_type=KeyboardType.REPLY,
    )),
])


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def main() -> None:
    """Run the reply keyboard dialog test bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("reply_keyboard_dialog_bot")

    token, chat_id = get_credentials()

    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    # Register commands for direct class usage
    app.register_command(DialogCommand(
        command="/choice",
        description="Test ChoiceDialog with keyboard_type=REPLY (direct class)",
        dialog=choice_dialog,
    ))

    app.register_command(DialogCommand(
        command="/choice_factory",
        description="Test create_choice_dialog with KeyboardType.REPLY",
        dialog=choice_factory_dialog,
    ))

    app.register_command(DialogCommand(
        command="/confirm",
        description="Test ConfirmDialog with keyboard_type=REPLY (direct class)",
        dialog=confirm_dialog,
    ))

    app.register_command(DialogCommand(
        command="/confirm_cancel",
        description="Test ConfirmDialog with cancel button",
        dialog=confirm_cancel_dialog,
    ))

    app.register_command(DialogCommand(
        command="/confirm_factory",
        description="Test create_confirm_dialog with KeyboardType.REPLY",
        dialog=confirm_factory_dialog,
    ))

    app.register_command(DialogCommand(
        command="/paginated",
        description="Test PaginatedChoiceDialog with keyboard_type=REPLY (direct class)",
        dialog=paginated_dialog,
    ))

    app.register_command(DialogCommand(
        command="/paginated_factory",
        description="Test create_paginated_choice_dialog with KeyboardType.REPLY",
        dialog=paginated_factory_dialog,
    ))

    app.register_command(DialogCommand(
        command="/dynamic_choice",
        description="Test dynamic choices via callable",
        dialog=dynamic_choice_dialog,
    ))

    app.register_command(DialogCommand(
        command="/branch",
        description="Test ChoiceBranchDialog with keyboard_type=REPLY (direct class)",
        dialog=branch_dialog,
    ))

    app.register_command(DialogCommand(
        command="/branch_factory",
        description="Test create_choice_branch_dialog with KeyboardType.REPLY",
        dialog=branch_factory_dialog,
    ))

    app.register_command(DialogCommand(
        command="/dynamic_branch",
        description="Test dynamic branches via callable",
        dialog=dynamic_branch_dialog,
    ))

    # Handler commands to show results
    async def handle_choice_result(result: Any) -> None:
        """Handle choice dialog result."""
        if is_cancelled(result):
            await app.send_messages("❌ Choice dialog was cancelled.")
        else:
            await app.send_messages(f"✅ Selected: {result}")

    app.register_command(DialogCommand(
        command="/choice_handler",
        description="Test ChoiceDialog with handler",
        dialog=DialogHandler(
            dialog=choice_dialog,
            on_complete=handle_choice_result,
        ),
    ))

    async def handle_confirm_result(result: Any) -> None:
        """Handle confirm dialog result."""
        if is_cancelled(result):
            await app.send_messages("❌ Confirm dialog was cancelled.")
        else:
            await app.send_messages(f"✅ Confirmed: {result}")

    app.register_command(DialogCommand(
        command="/confirm_handler",
        description="Test ConfirmDialog with handler",
        dialog=DialogHandler(
            dialog=confirm_dialog,
            on_complete=handle_confirm_result,
        ),
    ))

    # Info command
    info_text = (
        "<b>Reply Keyboard Dialog Bot</b>\n\n"
        "Tests merged dialog classes with keyboard_type=KeyboardType.REPLY:\n"
        "• ChoiceDialog - Choice dialog using reply keyboard\n"
        "• ConfirmDialog - Confirm dialog using reply keyboard\n"
        "• PaginatedChoiceDialog - Paginated choice dialog using reply keyboard\n"
        "• ChoiceBranchDialog - Choice branch dialog using reply keyboard\n"
        "• Factory functions with keyboard_type=KeyboardType.REPLY\n"
        "• Text matching for button labels\n"
        "• Cancel functionality\n"
        "• Dynamic choices via callable\n"
        "• Dynamic branches via callable\n\n"
        "<b>Commands:</b>\n"
        "• /choice - Test ChoiceDialog with keyboard_type=REPLY (direct class)\n"
        "• /choice_factory - Test create_choice_dialog with KeyboardType.REPLY\n"
        "• /confirm - Test ConfirmDialog with keyboard_type=REPLY (direct class)\n"
        "• /confirm_cancel - Test ConfirmDialog with cancel\n"
        "• /confirm_factory - Test create_confirm_dialog with KeyboardType.REPLY\n"
        "• /paginated - Test PaginatedChoiceDialog with keyboard_type=REPLY (direct class)\n"
        "• /paginated_factory - Test create_paginated_choice_dialog with KeyboardType.REPLY\n"
        "• /dynamic_choice - Test dynamic choices via callable\n"
        "• /branch - Test ChoiceBranchDialog with keyboard_type=REPLY (direct class)\n"
        "• /branch_factory - Test create_choice_branch_dialog with KeyboardType.REPLY\n"
        "• /dynamic_branch - Test dynamic branches via callable\n"
        "• /choice_handler - Test ChoiceDialog with handler\n"
        "• /confirm_handler - Test ConfirmDialog with handler"
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
            f"⌨️ <b>Reply Keyboard Dialog Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("send_startup_and_run: starting")
        await app.run()

    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
