"""Dialog system for interactive multi-step Telegram conversations."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .bot_application import get_logger


class DialogState(Enum):
    """State of a dialog conversation."""
    INACTIVE = "inactive"
    ACTIVE = "active"
    AWAITING_TEXT = "awaiting_text"
    COMPLETE = "complete"


@dataclass
class DialogResponse:
    """Response from a dialog - text with optional inline keyboard.
    
    Attributes:
        text: The message text to send/edit.
        keyboard: Optional InlineKeyboardMarkup for buttons.
        edit_message: If True, edit the existing message. If False, send new.
    """
    text: str
    keyboard: Optional[object] = None  # InlineKeyboardMarkup
    edit_message: bool = True


class Dialog(ABC):
    """Base class for interactive multi-step conversations.
    
    The dialog fully owns the conversation once activated. TelegramCommandsEvent
    delegates all user input to the dialog until it completes.
    
    Every dialog MUST include a Done button in all keyboard states.
    """

    def __init__(self) -> None:
        self.state = DialogState.INACTIVE

    @property
    def is_active(self) -> bool:
        """Check if the dialog is currently active."""
        return self.state in (DialogState.ACTIVE, DialogState.AWAITING_TEXT)

    @abstractmethod
    def start(self) -> DialogResponse:
        """Start the dialog, return initial message with keyboard."""
        ...

    @abstractmethod
    def handle_callback(self, callback_data: str) -> DialogResponse:
        """Handle inline keyboard button press."""
        ...

    def handle_text_input(self, text: str) -> Optional[DialogResponse]:
        """Handle text input from user.
        
        Default behavior: If dialog is AWAITING_TEXT, subclass handles it.
        If dialog is ACTIVE (expecting button press), return None (caller should
        send clarifying message and re-send keyboard).
        """
        if self.state == DialogState.AWAITING_TEXT:
            return self._process_text_value(text)
        # If ACTIVE, return None - DialogCommand will handle sending clarifying 
        # message followed by re-sending the keyboard
        return None

    def get_current_keyboard_response(self) -> Optional[DialogResponse]:
        """Get the current keyboard to display. Subclasses should override."""
        return None

    def get_unexpected_text_message(self) -> str:
        """Get the message to show when user sends text instead of clicking button."""
        return "Please select an option from the buttons below, or click Done to exit."

    @abstractmethod
    def _process_text_value(self, text: str) -> DialogResponse:
        """Subclass implements actual text value processing."""
        ...

    def done(self) -> DialogResponse:
        """Complete the dialog."""
        self.state = DialogState.COMPLETE
        logger = get_logger()
        logger.info("dialog_done")
        return DialogResponse(text="Dialog completed.", keyboard=None, edit_message=False)
