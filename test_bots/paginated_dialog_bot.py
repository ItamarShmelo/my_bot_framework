"""Test bot for PaginatedChoiceDialog.

Tests:
- PaginatedChoiceDialog with static items
- PaginatedChoiceDialog with dynamic items (callable)
- Different page sizes
- "More..." button behavior and text input selection
- Cancel functionality
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    DialogCommand,
    DialogHandler,
    PaginatedChoiceDialog,
    is_cancelled,
    get_app,
    get_logger,
)


def get_credentials() -> Tuple[str, str]:
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
# SAMPLE DATA
# =============================================================================

# Short list - should NOT show "More..." button
SHORT_ITEMS: List[Tuple[str, str]] = [
    ("Apple", "apple"),
    ("Banana", "banana"),
    ("Cherry", "cherry"),
]

# Long list - should show "More..." button with default page_size=5
EXPENSE_ITEMS: List[Tuple[str, str]] = [
    ("Rent $1200", "rent"),
    ("Groceries $95", "groceries"),
    ("Electric $85", "electric"),
    ("Internet $60", "internet"),
    ("Phone $45", "phone"),
    ("Gas $40", "gas"),
    ("Insurance $150", "insurance"),
    ("Subscriptions $30", "subscriptions"),
    ("Dining Out $120", "dining"),
    ("Entertainment $50", "entertainment"),
    ("Gym $25", "gym"),
    ("Clothing $80", "clothing"),
]

# Very long list - for testing with many items
COUNTRY_ITEMS: List[Tuple[str, str]] = [
    ("United States", "us"),
    ("Canada", "ca"),
    ("United Kingdom", "uk"),
    ("Germany", "de"),
    ("France", "fr"),
    ("Italy", "it"),
    ("Spain", "es"),
    ("Netherlands", "nl"),
    ("Belgium", "be"),
    ("Switzerland", "ch"),
    ("Austria", "at"),
    ("Sweden", "se"),
    ("Norway", "no"),
    ("Denmark", "dk"),
    ("Finland", "fi"),
    ("Poland", "pl"),
    ("Australia", "au"),
    ("New Zealand", "nz"),
    ("Japan", "jp"),
    ("South Korea", "kr"),
]


def get_dynamic_items(context: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Generate items dynamically based on context.
    
    Args:
        context: Dialog context dictionary.
        
    Returns:
        List of (label, callback_data) tuples.
    """
    # Simulate dynamic item generation
    base_items = [
        ("Task 1: Review code", "task_1"),
        ("Task 2: Write tests", "task_2"),
        ("Task 3: Update docs", "task_3"),
        ("Task 4: Fix bug #123", "task_4"),
        ("Task 5: Deploy staging", "task_5"),
        ("Task 6: Code review", "task_6"),
        ("Task 7: Sprint planning", "task_7"),
        ("Task 8: Standup meeting", "task_8"),
    ]
    return base_items


# =============================================================================
# COMMAND HANDLERS (on_complete callbacks for DialogHandler)
# =============================================================================

async def on_short_complete(result: Any) -> None:
    """Handle short dialog result.
    
    Args:
        result: The dialog result.
    """
    logger = get_logger()
    if is_cancelled(result):
        logger.info("short_dialog: User cancelled")
        await get_app().send_messages("Selection cancelled.")
    else:
        logger.info("short_dialog: Selected %s", result)
        await get_app().send_messages(f"You selected: {result}")


async def on_expenses_complete(result: Any) -> None:
    """Handle expenses dialog result.
    
    Args:
        result: The dialog result.
    """
    logger = get_logger()
    if is_cancelled(result):
        logger.info("expenses_dialog: User cancelled")
        await get_app().send_messages("Expense removal cancelled.")
    else:
        # Find the label for the selected item
        label = next((lbl for lbl, cb in EXPENSE_ITEMS if cb == result), result)
        logger.info("expenses_dialog: Removed %s", label)
        await get_app().send_messages(f"Removed expense: {label}")


async def on_countries_complete(result: Any) -> None:
    """Handle countries dialog result.
    
    Args:
        result: The dialog result.
    """
    logger = get_logger()
    if is_cancelled(result):
        logger.info("countries_dialog: User cancelled")
        await get_app().send_messages("Country selection cancelled.")
    else:
        label = next((lbl for lbl, cb in COUNTRY_ITEMS if cb == result), result)
        logger.info("countries_dialog: Selected %s (%s)", label, result)
        await get_app().send_messages(f"Selected country: {label} (code: {result})")


async def on_tasks_complete(result: Any) -> None:
    """Handle tasks dialog result.
    
    Args:
        result: The dialog result.
    """
    logger = get_logger()
    if is_cancelled(result):
        logger.info("tasks_dialog: User cancelled")
        await get_app().send_messages("Task selection cancelled.")
    else:
        logger.info("tasks_dialog: Starting %s", result)
        await get_app().send_messages(f"Starting work on: {result}")


async def on_nocancel_complete(result: Any) -> None:
    """Handle nocancel dialog result.
    
    Args:
        result: The dialog result.
    """
    logger = get_logger()
    if is_cancelled(result):
        logger.info("nocancel_dialog: Cancelled (unexpected)")
        await get_app().send_messages("Cancelled (unexpected).")
    else:
        logger.info("nocancel_dialog: Selected %s", result)
        await get_app().send_messages(f"Selected: {result}")


# =============================================================================
# DIALOG DEFINITIONS (wrapped with DialogHandler for on_complete callbacks)
# =============================================================================

# /short - Tests with a short list (no "More..." button)
short_dialog = DialogHandler(
    PaginatedChoiceDialog(
        prompt="Select a fruit:",
        items=SHORT_ITEMS,
        page_size=5,
    ),
    on_complete=on_short_complete,
)

# /expenses - Tests with a longer list (shows "More..." button)
expenses_dialog = DialogHandler(
    PaginatedChoiceDialog(
        prompt="Select expense to remove:",
        items=EXPENSE_ITEMS,
        page_size=5,
    ),
    on_complete=on_expenses_complete,
)

# /countries - Tests with many items and smaller page size
countries_dialog = DialogHandler(
    PaginatedChoiceDialog(
        prompt="Select your country:",
        items=COUNTRY_ITEMS,
        page_size=3,
        more_label="Show all countries...",
    ),
    on_complete=on_countries_complete,
)

# /tasks - Tests with dynamic items
tasks_dialog = DialogHandler(
    PaginatedChoiceDialog(
        prompt="Select a task to work on:",
        items=get_dynamic_items,
        page_size=4,
        more_label="View all tasks...",
    ),
    on_complete=on_tasks_complete,
)

# /nocancel - Tests without cancel button
nocancel_dialog = DialogHandler(
    PaginatedChoiceDialog(
        prompt="Select an option (no cancel):",
        items=EXPENSE_ITEMS[:8],
        page_size=3,
        include_cancel=False,
    ),
    on_complete=on_nocancel_complete,
)


def main() -> None:
    """Run the paginated dialog test bot."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("paginated_dialog_bot")
    
    token, chat_id = get_credentials()
    app = BotApplication.initialize(token=token, chat_id=chat_id, logger=logger)
    
    # Register info command (REQUIRED for all test bots)
    info_text = (
        "<b>Paginated Dialog Bot</b>\n\n"
        "Tests:\n"
        "• <b>PaginatedChoiceDialog</b> - Paginated keyboard selection\n"
        "• Static items list\n"
        "• Dynamic items via callable\n"
        "• Different page sizes\n"
        "• \"More...\" button behavior\n"
        "• Text input selection for remaining items\n"
        "• Cancel functionality"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))
    
    # Register commands
    app.register_command(SimpleCommand(
        "/start",
        "Show available commands",
        lambda: (
            "Paginated Dialog Test Bot\n\n"
            "Commands:\n"
            "/short - Short list (no pagination)\n"
            "/expenses - Expense list (5 items per page)\n"
            "/countries - Country list (3 items per page)\n"
            "/tasks - Dynamic task list\n"
            "/nocancel - List without cancel button"
        ),
    ))
    
    app.register_command(DialogCommand(
        "/short",
        "Test short list (no More button)",
        short_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/expenses",
        "Test expense list with pagination",
        expenses_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/countries",
        "Test country list with small page size",
        countries_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/tasks",
        "Test dynamic items",
        tasks_dialog,
    ))
    
    app.register_command(DialogCommand(
        "/nocancel",
        "Test without cancel button",
        nocancel_dialog,
    ))
    
    # Send startup message and run
    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"🤖 <b>Paginated Dialog Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting paginated_dialog_bot...")
        await app.run()
    
    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
