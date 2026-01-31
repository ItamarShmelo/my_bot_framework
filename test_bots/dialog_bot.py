"""Dialog bot testing the new Dialog composite system.

Tests ALL dialog types:
- ChoiceDialog: User selects from keyboard options
- UserInputDialog: User enters text with optional validation
- ConfirmDialog: Yes/No prompt
- SequenceDialog: Run dialogs in order with named values
- BranchDialog: Condition-based branching
- ChoiceBranchDialog: User selects branch via keyboard
- LoopDialog: Repeat until exit condition
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    DialogCommand,
    # New dialog types
    ChoiceDialog,
    UserInputDialog,
    ConfirmDialog,
    SequenceDialog,
    BranchDialog,
    ChoiceBranchDialog,
    LoopDialog,
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


# =============================================================================
# DIALOG DEFINITIONS
# =============================================================================

# /simple - Tests SequenceDialog with ChoiceDialog and UserInputDialog
simple_dialog = SequenceDialog([
    ("name", UserInputDialog("Enter your name:")),
    ("mood", ChoiceDialog("How are you?", [
        ("Great", "great"),
        ("Good", "good"),
        ("Okay", "okay"),
    ])),
])


# /confirm - Tests ConfirmDialog with custom labels
confirm_dialog = ConfirmDialog(
    prompt="Do you want to continue?",
    yes_label="Yes, continue",
    no_label="No, cancel",
)


# /validated - Tests UserInputDialog with validator
def validate_number(value: str) -> tuple[bool, str]:
    """Validate that input is a number between 1-100."""
    if not value.isdigit():
        return False, "Please enter a valid number."
    num = int(value)
    if not 1 <= num <= 100:
        return False, "Number must be between 1 and 100."
    return True, ""


validated_dialog = UserInputDialog(
    prompt="Enter a number between 1-100:",
    validator=validate_number,
)


# /dynamic - Tests dynamic choices based on context
dynamic_dialog = SequenceDialog([
    ("category", ChoiceDialog("Select category:", [
        ("Programming", "prog"),
        ("Design", "design"),
    ])),
    ("tool", ChoiceDialog(
        prompt="Select tool:",
        choices=lambda ctx: [
            ("Python", "python"),
            ("TypeScript", "ts"),
            ("Go", "go"),
        ] if ctx.get("category") == "prog" else [
            ("Figma", "figma"),
            ("Sketch", "sketch"),
            ("Adobe XD", "xd"),
        ],
    )),
])


# /branch - Tests ChoiceBranchDialog (keyboard-driven branching)
branch_dialog = ChoiceBranchDialog(
    prompt="Select your path:",
    branches={
        "quick": ("Quick Setup", UserInputDialog("Enter your name:")),
        "full": ("Full Setup", SequenceDialog([
            ("name", UserInputDialog("Enter your name:")),
            ("email", UserInputDialog("Enter your email:")),
            ("notify", ConfirmDialog("Enable notifications?")),
        ])),
    }
)


# /condition - Tests BranchDialog with condition function
condition_dialog = SequenceDialog([
    ("age", UserInputDialog(
        "Enter your age:",
        validator=lambda v: (v.isdigit() and int(v) > 0, "Please enter a valid age."),
    )),
    ("content", BranchDialog(
        condition=lambda ctx: "adult" if int(ctx.get("age", "0")) >= 18 else "minor",
        branches={
            "adult": ChoiceDialog("Select plan:", [
                ("Pro", "pro"),
                ("Enterprise", "ent"),
            ]),
            "minor": ChoiceDialog("Select plan:", [
                ("Student", "student"),
                ("Free", "free"),
            ]),
        }
    )),
])


# /loop - Tests LoopDialog with exit_value
loop_dialog = LoopDialog(
    dialog=UserInputDialog("Enter an item (or 'done' to finish):"),
    exit_value="done",
)


# /loopvalid - Tests LoopDialog with exit_condition and max_iterations
def is_valid_email(value: str) -> bool:
    """Check if value looks like an email."""
    return "@" in value and "." in value


loop_valid_dialog = LoopDialog(
    dialog=UserInputDialog("Enter a valid email:"),
    exit_condition=is_valid_email,
    max_iterations=5,
)


# /full - Tests full composite: Sequence + Branch + Loop + Confirm
full_onboarding = SequenceDialog([
    ("name", UserInputDialog("Enter your name:")),
    ("role", ChoiceBranchDialog(
        prompt="Select your role:",
        branches={
            "dev": ("Developer", SequenceDialog([
                ("lang", ChoiceDialog("Primary language:", [
                    ("Python", "py"),
                    ("TypeScript", "ts"),
                    ("Go", "go"),
                ])),
                ("experience", UserInputDialog("Years of experience:")),
            ])),
            "design": ("Designer", SequenceDialog([
                ("tool", ChoiceDialog("Primary tool:", [
                    ("Figma", "figma"),
                    ("Sketch", "sketch"),
                ])),
            ])),
            "other": ("Other", UserInputDialog("Describe your role:")),
        }
    )),
    ("skills", LoopDialog(
        dialog=UserInputDialog("Add a skill (or 'done'):"),
        exit_value="done",
    )),
    ("confirm", ConfirmDialog("Save your profile?")),
])


# =============================================================================
# MAIN
# =============================================================================

def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("dialog_bot")
    
    token, chat_id = get_credentials()
    
    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )
    
    # Register dialog commands
    app.register_command(DialogCommand(
        command="/simple",
        description="Simple sequence: name + mood",
        dialog=simple_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/confirm",
        description="Yes/No confirmation dialog",
        dialog=confirm_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/validated",
        description="Input with validation (number 1-100)",
        dialog=validated_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/dynamic",
        description="Dynamic choices based on previous selection",
        dialog=dynamic_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/branch",
        description="Keyboard-driven branching",
        dialog=branch_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/condition",
        description="Condition-based branching (age check)",
        dialog=condition_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/loop",
        description="Loop until 'done' entered",
        dialog=loop_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/loopvalid",
        description="Loop until valid email (max 5 attempts)",
        dialog=loop_valid_dialog,
    ))
    
    app.register_command(DialogCommand(
        command="/full",
        description="Full onboarding: name + role + skills + confirm",
        dialog=full_onboarding,
    ))
    
    # Register info command
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: (
            "<b>Dialog Bot</b>\n\n"
            "Tests the new Dialog composite system:\n"
            "• <b>/simple</b> - SequenceDialog, ChoiceDialog, UserInputDialog\n"
            "• <b>/confirm</b> - ConfirmDialog with custom labels\n"
            "• <b>/validated</b> - UserInputDialog with validation\n"
            "• <b>/dynamic</b> - Dynamic choices based on context\n"
            "• <b>/branch</b> - ChoiceBranchDialog (keyboard branching)\n"
            "• <b>/condition</b> - BranchDialog with condition function\n"
            "• <b>/loop</b> - LoopDialog with exit_value\n"
            "• <b>/loopvalid</b> - LoopDialog with exit_condition\n"
            "• <b>/full</b> - Complete onboarding flow"
        ),
    ))
    
    logger.info("Starting dialog_bot...")
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
