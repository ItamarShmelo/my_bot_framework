"""my-bot-framework - A modular Telegram bot framework.

This framework provides the core infrastructure for building Telegram bots
with event-driven architecture, interactive dialogs, and message queuing.

Usage:
    from my_bot_framework import BotApplication
    
    app = BotApplication.initialize(
        token="YOUR_BOT_TOKEN",
        chat_id="YOUR_CHAT_ID",
        logger=your_logger,
    )
    app.register_event(my_event)
    app.register_command(my_command)
    await app.run()
"""

from .bot_application import (
    BotApplication,
    get_app,
    get_bot,
    get_chat_id,
    get_queue,
    get_stop_event,
    get_logger,
)
from .event import (
    Event,
    TimeEvent,
    ActivateOnConditionEvent,
    TelegramCommandsEvent,
    EditableField,
    EditableMixin,
    Command,
    SimpleCommand,
    DialogCommand,
    flush_pending_updates,
    poll_updates,
    get_chat_id_from_update,
)
from .telegram_utilities import (
    TelegramMessage,
    TelegramTextMessage,
    TelegramImageMessage,
    TelegramOptionsMessage,
    TelegramEditMessage,
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
)
from .dialog import (
    Dialog,
    DialogState,
    DialogResponse,
    DialogResult,
    DialogHandler,
    ChoiceDialog,
    UserInputDialog,
    ConfirmDialog,
    SequenceDialog,
    BranchDialog,
    ChoiceBranchDialog,
    LoopDialog,
    UpdatePollerMixin,
    CANCELLED,
    is_cancelled,
    DIALOG_DEBUG,
    set_dialog_debug,
)
from .utilities import (
    CallUpdatesInternalState,
    divide_message_to_chunks,
    format_message_html,
)

__all__ = [
    # BotApplication
    "BotApplication",
    "get_app",
    "get_bot",
    "get_chat_id",
    "get_queue",
    "get_stop_event",
    "get_logger",
    # Events
    "Event",
    "TimeEvent",
    "ActivateOnConditionEvent",
    "TelegramCommandsEvent",
    "EditableField",
    "EditableMixin",
    # Commands
    "Command",
    "SimpleCommand",
    "DialogCommand",
    # Telegram utilities
    "TelegramMessage",
    "TelegramTextMessage",
    "TelegramImageMessage",
    "TelegramOptionsMessage",
    "TelegramEditMessage",
    "TelegramCallbackAnswerMessage",
    "TelegramRemoveKeyboardMessage",
    # Dialog
    "Dialog",
    "DialogState",
    "DialogResponse",
    "DialogResult",
    "DialogHandler",
    "ChoiceDialog",
    "UserInputDialog",
    "ConfirmDialog",
    "SequenceDialog",
    "BranchDialog",
    "ChoiceBranchDialog",
    "LoopDialog",
    # Mixins
    "UpdatePollerMixin",
    # Sentinels and Debug
    "CANCELLED",
    "is_cancelled",
    "DIALOG_DEBUG",
    "set_dialog_debug",
    # Utilities
    "CallUpdatesInternalState",
    "divide_message_to_chunks",
    "format_message_html",
    "flush_pending_updates",
    "poll_updates",
    "get_chat_id_from_update",
]
