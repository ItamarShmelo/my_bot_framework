"""Dialog bot testing DialogCommand and Dialog system.

Tests:
- DialogCommand registration
- Dialog state machine (INACTIVE -> ACTIVE -> COMPLETE)
- Inline keyboard handling
- Text input handling in dialogs
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from my_bot_framework import (
    BotApplication,
    SimpleCommand,
    DialogCommand,
    Dialog,
    DialogState,
    DialogResponse,
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


class SettingsDialog(Dialog):
    """Simple settings dialog with multiple options."""
    
    def __init__(self):
        super().__init__()
        self.notifications_enabled = True
        self.theme = "light"
    
    def start(self) -> DialogResponse:
        self.state = DialogState.ACTIVE
        return DialogResponse(
            text=self._build_settings_text(),
            keyboard=self._build_keyboard(),
        )
    
    def handle_callback(self, callback_data: str) -> DialogResponse:
        if callback_data == "done":
            return self.done()
        
        if callback_data == "toggle_notifications":
            self.notifications_enabled = not self.notifications_enabled
            return DialogResponse(
                text=self._build_settings_text(),
                keyboard=self._build_keyboard(),
                edit_message=True,
            )
        
        if callback_data == "toggle_theme":
            self.theme = "dark" if self.theme == "light" else "light"
            return DialogResponse(
                text=self._build_settings_text(),
                keyboard=self._build_keyboard(),
                edit_message=True,
            )
        
        return None  # Unknown callback
    
    def _process_text_value(self, text: str) -> DialogResponse:
        # This dialog doesn't accept text input
        return DialogResponse(
            text="Please use the buttons to change settings.",
            keyboard=self._build_keyboard(),
        )
    
    def get_current_keyboard_response(self) -> DialogResponse:
        return DialogResponse(
            text=self._build_settings_text(),
            keyboard=self._build_keyboard(),
        )
    
    def _build_settings_text(self) -> str:
        notif_status = "ON" if self.notifications_enabled else "OFF"
        return (
            "<b>Settings</b>\n\n"
            f"Notifications: {notif_status}\n"
            f"Theme: {self.theme.capitalize()}"
        )
    
    def _build_keyboard(self) -> InlineKeyboardMarkup:
        notif_text = "🔔 Disable Notifications" if self.notifications_enabled else "🔕 Enable Notifications"
        theme_text = "🌙 Dark Theme" if self.theme == "light" else "☀️ Light Theme"
        
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(notif_text, callback_data="toggle_notifications")],
            [InlineKeyboardButton(theme_text, callback_data="toggle_theme")],
            [InlineKeyboardButton("✅ Done", callback_data="done")],
        ])
    
    def done(self) -> DialogResponse:
        self.state = DialogState.COMPLETE
        notif_status = "enabled" if self.notifications_enabled else "disabled"
        return DialogResponse(
            text=f"Settings saved!\nNotifications: {notif_status}\nTheme: {self.theme}",
            keyboard=None,
            edit_message=False,
        )


class InputDialog(Dialog):
    """Dialog that accepts text input."""
    
    def __init__(self):
        super().__init__()
        self.name = None
    
    def start(self) -> DialogResponse:
        self.state = DialogState.AWAITING_TEXT
        return DialogResponse(
            text="Please enter your name:",
            keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="done")],
            ]),
        )
    
    def handle_callback(self, callback_data: str) -> DialogResponse:
        if callback_data == "done":
            return self.done()
        return None
    
    def _process_text_value(self, text: str) -> DialogResponse:
        self.name = text
        self.state = DialogState.COMPLETE
        return DialogResponse(
            text=f"Hello, {self.name}! Nice to meet you.",
            keyboard=None,
            edit_message=False,
        )
    
    def get_current_keyboard_response(self) -> DialogResponse:
        return DialogResponse(
            text="Please enter your name:",
            keyboard=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="done")],
            ]),
        )


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
        command="/settings",
        description="Open settings dialog",
        dialog=SettingsDialog(),
    ))
    
    app.register_command(DialogCommand(
        command="/greet",
        description="Greeting dialog with text input",
        dialog=InputDialog(),
    ))
    
    # Register info command
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests",
        message_builder=lambda: (
            "<b>Dialog Bot</b>\n\n"
            "Tests interactive dialog system:\n"
            "• DialogCommand registration\n"
            "• Dialog state machine (INACTIVE → ACTIVE → COMPLETE)\n"
            "• DialogState.AWAITING_TEXT for text input\n"
            "• Inline keyboard button handling\n"
            "• Message editing in dialogs"
        ),
    ))
    
    logger.info("Starting dialog_bot...")
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
