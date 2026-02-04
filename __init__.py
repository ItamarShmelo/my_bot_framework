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
    get_stop_event,
    get_logger,
)
from .event import (
    Event,
    ActivateOnConditionEvent,
    CommandsEvent,
    Command,
    SimpleCommand,
    DialogCommand,
    Condition,
    MessageBuilder,
    FunctionCondition,
    FunctionMessageBuilder,
)
from .editable import (
    EditableAttribute,
    EditableMixin,
)
from .polling import (
    UpdatePollerMixin,
    flush_pending_updates,
    poll_updates,
    get_chat_id_from_update,
    get_next_update_id,
    set_next_update_id,
)
from .telegram_utilities import (
    TelegramMessage,
    TelegramTextMessage,
    TelegramImageMessage,
    TelegramDocumentMessage,
    TelegramOptionsMessage,
    TelegramEditMessage,
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
    InvalidHtmlError,
)
from .dialog import (
    Dialog,
    DialogState,
    DialogResponse,
    DialogResult,
    DialogHandler,
    ChoiceDialog,
    PaginatedChoiceDialog,
    UserInputDialog,
    ConfirmDialog,
    SequenceDialog,
    BranchDialog,
    ChoiceBranchDialog,
    LoopDialog,
    EditEventDialog,
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
from .event_examples import (
    TimeEvent,
    ThresholdEvent,
    create_threshold_event,
    create_file_change_event,
)

__all__ = [
    # BotApplication
    "BotApplication",
    "get_app",
    "get_bot",
    "get_chat_id",
    "get_stop_event",
    "get_logger",
    # Events
    "Event",
    "ActivateOnConditionEvent",
    "CommandsEvent",
    "EditableAttribute",
    "EditableMixin",
    "Condition",
    "MessageBuilder",
    "FunctionCondition",
    "FunctionMessageBuilder",
    # Commands
    "Command",
    "SimpleCommand",
    "DialogCommand",
    # Telegram utilities
    "TelegramMessage",
    "TelegramTextMessage",
    "TelegramImageMessage",
    "TelegramDocumentMessage",
    "TelegramOptionsMessage",
    "TelegramEditMessage",
    "TelegramCallbackAnswerMessage",
    "TelegramRemoveKeyboardMessage",
    "InvalidHtmlError",
    # Dialog
    "Dialog",
    "DialogState",
    "DialogResponse",
    "DialogResult",
    "DialogHandler",
    "ChoiceDialog",
    "PaginatedChoiceDialog",
    "UserInputDialog",
    "ConfirmDialog",
    "SequenceDialog",
    "BranchDialog",
    "ChoiceBranchDialog",
    "LoopDialog",
    "EditEventDialog",
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
    "get_next_update_id",
    "set_next_update_id",
    # Event Factories
    "create_threshold_event",
    "create_file_change_event",
    # Event Examples (subclasses of ActivateOnConditionEvent)
    "TimeEvent",
    "ThresholdEvent",
]
