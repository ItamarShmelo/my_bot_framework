"""Utilities bot testing formatting utilities and validators.

Tests:
- format_numbered_list - Format items as numbered list
- format_bullet_list - Format items as bullet list
- format_key_value_pairs - Format key-value pairs
- divide_message_to_chunks - Split messages into chunks
- validate_positive_int - Validate positive integers
- validate_positive_float - Validate positive floats
- validate_int_range - Validate integers in range
- validate_float_range - Validate floats in range
- validate_date_format - Validate date format strings
- validate_regex - Validate regex patterns
"""

import asyncio
import logging
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
    format_numbered_list,
    format_bullet_list,
    format_key_value_pairs,
    divide_message_to_chunks,
    validate_positive_int,
    validate_positive_float,
    validate_int_range,
    validate_float_range,
    validate_date_format,
    validate_regex,
)


def get_credentials():
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


def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("utilities_bot")
    
    token, chat_id = get_credentials()
    
    # Initialize the bot
    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )
    
    # Register info command
    info_text = (
        "<b>Utilities Bot</b>\n\n"
        "Tests formatting utilities and validators:\n\n"
        "<b>Utilities:</b>\n"
        "• format_numbered_list - Format items as numbered list\n"
        "• format_bullet_list - Format items as bullet list\n"
        "• format_key_value_pairs - Format key-value pairs\n"
        "• divide_message_to_chunks - Split messages into chunks\n\n"
        "<b>Validators:</b>\n"
        "• validate_positive_int - Validate positive integers\n"
        "• validate_positive_float - Validate positive floats\n"
        "• validate_int_range - Validate integers in range\n"
        "• validate_float_range - Validate floats in range\n"
        "• validate_date_format - Validate date format strings\n"
        "• validate_regex - Validate regex patterns"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: info_text,
    ))
    
    # =============================================================================
    # UTILITY COMMANDS
    # =============================================================================
    
    # /numbered - Test format_numbered_list
    app.register_command(SimpleCommand(
        command="/numbered",
        description="Show format_numbered_list example",
        message_builder=lambda: (
            "<b>format_numbered_list Example</b>\n\n"
            f"{format_numbered_list(['Apple', 'Banana', 'Cherry'])}\n\n"
            f"Starting at 5:\n{format_numbered_list(['First', 'Second'], start=5)}"
        ),
    ))
    
    # /bullet - Test format_bullet_list
    app.register_command(SimpleCommand(
        command="/bullet",
        description="Show format_bullet_list example",
        message_builder=lambda: (
            "<b>format_bullet_list Example</b>\n\n"
            f"{format_bullet_list(['Apple', 'Banana', 'Cherry'])}\n\n"
            f"Custom bullet:\n{format_bullet_list(['One', 'Two'], bullet='-')}"
        ),
    ))
    
    # /keyvalue - Test format_key_value_pairs
    app.register_command(SimpleCommand(
        command="/keyvalue",
        description="Show format_key_value_pairs example",
        message_builder=lambda: (
            "<b>format_key_value_pairs Example</b>\n\n"
            f"{format_key_value_pairs([('Name', 'John'), ('Age', '30'), ('City', 'New York')])}\n\n"
            f"Custom separator:\n{format_key_value_pairs([('A', '1'), ('B', '2')], separator=' = ')}"
        ),
    ))
    
    # /chunks - Test divide_message_to_chunks
    app.register_command(SimpleCommand(
        command="/chunks",
        description="Show divide_message_to_chunks example",
        message_builder=lambda: (
            "<b>divide_message_to_chunks Example</b>\n\n"
            "Original message (50 chars):\n"
            f"'{'A' * 50}'\n\n"
            f"Chunked into 20 chars:\n"
            f"{format_numbered_list([f'Chunk {i+1}: {chunk}' for i, chunk in enumerate(divide_message_to_chunks('A' * 50, 20))])}"
        ),
    ))
    
    # =============================================================================
    # VALIDATOR COMMANDS (using DialogCommand with UserInputDialog)
    # =============================================================================
    
    # /validate_int - Test validate_positive_int
    app.register_command(DialogCommand(
        command="/validate_int",
        description="Test validate_positive_int on user input",
        dialog=DialogHandler(
            dialog=UserInputDialog(
                prompt="Enter a positive integer:",
                validator=validate_positive_int,
            ),
            on_complete=lambda result: f"✅ Valid positive integer: <b>{result}</b>",
        ),
    ))
    
    # /validate_float - Test validate_positive_float
    app.register_command(DialogCommand(
        command="/validate_float",
        description="Test validate_positive_float on user input",
        dialog=DialogHandler(
            dialog=UserInputDialog(
                prompt="Enter a positive float:",
                validator=validate_positive_float,
            ),
            on_complete=lambda result: f"✅ Valid positive float: <b>{result}</b>",
        ),
    ))
    
    # /validate_range - Test validate_int_range(1, 100)
    app.register_command(DialogCommand(
        command="/validate_range",
        description="Test validate_int_range(1, 100) on user input",
        dialog=DialogHandler(
            dialog=UserInputDialog(
                prompt="Enter an integer between 1 and 100:",
                validator=validate_int_range(1, 100),
            ),
            on_complete=lambda result: f"✅ Valid integer in range [1, 100]: <b>{result}</b>",
        ),
    ))
    
    # /validate_float_range - Test validate_float_range(0.0, 1.0)
    app.register_command(DialogCommand(
        command="/validate_float_range",
        description="Test validate_float_range(0.0, 1.0) on user input",
        dialog=DialogHandler(
            dialog=UserInputDialog(
                prompt="Enter a float between 0.0 and 1.0:",
                validator=validate_float_range(0.0, 1.0),
            ),
            on_complete=lambda result: f"✅ Valid float in range [0.0, 1.0]: <b>{result}</b>",
        ),
    ))
    
    # /validate_date - Test validate_date_format("%Y-%m-%d")
    app.register_command(DialogCommand(
        command="/validate_date",
        description="Test validate_date_format('%Y-%m-%d') on user input",
        dialog=DialogHandler(
            dialog=UserInputDialog(
                prompt="Enter a date in YYYY-MM-DD format:",
                validator=validate_date_format("%Y-%m-%d", "YYYY-MM-DD"),
            ),
            on_complete=lambda result: f"✅ Valid date (YYYY-MM-DD): <b>{result}</b>",
        ),
    ))
    
    # /validate_email - Test validate_regex with email pattern
    email_validator = validate_regex(
        pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",
        error_msg="Invalid email format. Please enter a valid email address.",
    )
    app.register_command(DialogCommand(
        command="/validate_email",
        description="Test validate_regex with email pattern on user input",
        dialog=DialogHandler(
            dialog=UserInputDialog(
                prompt="Enter an email address:",
                validator=email_validator,
            ),
            on_complete=lambda result: f"✅ Valid email address: <b>{result}</b>",
        ),
    ))
    
    # Send startup message and run
    async def send_startup_and_run():
        await app.send_messages(
            f"🤖 <b>Utilities Bot Started</b>\n\n"
            f"{info_text}\n\n"
            f"💡 Type /commands to see all available commands."
        )
        logger.info("Starting utilities_bot...")
        await app.run()
    
    asyncio.run(send_startup_and_run())


if __name__ == "__main__":
    main()
