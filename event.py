"""Event system for the bot framework."""

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple, Union

from telegram import Bot, Update

from .telegram_utilities import (
    TelegramMessage,
    TelegramTextMessage,
    TelegramOptionsMessage,
    TelegramEditMessage,
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
)
from .accessors import get_bot, get_chat_id, get_logger
from .polling import (
    UpdatePollerMixin,
    flush_pending_updates,
    poll_updates,
    get_chat_id_from_update,
)

if TYPE_CHECKING:
    from .dialog import Dialog, DialogResponse

MINIMAL_TIME_BETWEEN_MESSAGES = 5.0 / 60.0


class EditableAttribute:
    """A runtime-editable attribute with parsing and validation.
    
    - `parse`: User-provided callable that receives string, returns typed value
    - `value` property: getter returns typed value, setter parses strings and validates
    - `validator`: Optional function that receives typed value, returns (is_valid, error_msg)
    """

    def __init__(
        self,
        name: str,
        field_type: type,
        initial_value: Any,
        parse: Callable[[str], Any],
        validator: Optional[Callable[[Any], Tuple[bool, str]]] = None,
    ) -> None:
        self.name = name
        self.field_type = field_type
        self._value = initial_value
        self.parse = parse
        self.validator = validator

    def validate(self, value: Any) -> Tuple[bool, str]:
        """Validate a typed value. Returns (is_valid, error_message)."""
        # Type check - field_type can be a single type or tuple of types
        if not isinstance(value, self.field_type):
            if isinstance(self.field_type, tuple):
                type_names = " or ".join(t.__name__ for t in self.field_type)
            else:
                type_names = self.field_type.__name__
            return False, f"Expected {type_names}, got {type(value).__name__}"

        # Custom validator
        if self.validator:
            return self.validator(value)

        return True, ""

    @property
    def value(self) -> Any:
        """Get the current value."""
        return self._value

    @value.setter
    def value(self, new_value: Any) -> None:
        """Set value - parses if string, then validates. Raises ValueError if invalid."""
        # If string, parse first
        if isinstance(new_value, str):
            new_value = self.parse(new_value)

        # Validate the (parsed) value
        is_valid, error = self.validate(new_value)
        if not is_valid:
            raise ValueError(error)
        self._value = new_value


class EditableMixin(ABC):
    """Mixin for objects with runtime-editable attributes.
    
    The `edited` property allows signaling that parameters have changed,
    triggering immediate re-processing in events that support it.
    """
    
    _edited: bool = False

    @property
    def editable_attributes(self) -> dict[str, "EditableAttribute"]:
        """Mapping of editable attributes."""
        if not hasattr(self, "_editable_attributes"):
            self._editable_attributes = {}
        return self._editable_attributes

    @editable_attributes.setter
    def editable_attributes(self, attributes: List["EditableAttribute"]) -> None:
        """Initialize the editable attribute mapping with validation."""
        self._init_editable_attributes(attributes)

    def _init_editable_attributes(self, attributes: List["EditableAttribute"]) -> None:
        """Validate and store editable attributes."""
        if not isinstance(attributes, list):
            raise TypeError("attributes must be a list of EditableAttribute")
        mapping: dict[str, EditableAttribute] = {}
        for attribute in attributes:
            if not isinstance(attribute, EditableAttribute):
                raise TypeError("All attributes must be EditableAttribute instances")
            if not isinstance(attribute.name, str) or not attribute.name:
                raise ValueError("EditableAttribute.name must be a non-empty string")
            if attribute.name in mapping:
                raise ValueError(f"Duplicate EditableAttribute name: {attribute.name}")
            mapping[attribute.name] = attribute
        self._editable_attributes = mapping

    @property
    def edited(self) -> bool:
        """Check if the object has been marked as edited."""
        return self._edited

    @edited.setter
    def edited(self, value: bool) -> None:
        """Set the edited flag."""
        logger = get_logger()
        logger.info("[%s] edited_flag_set value=%s", type(self).__name__, value)
        self._edited = value

    def edit(self, name: str, value: Any) -> None:
        """Edit an attribute by name (fail fast if missing)."""
        if name not in self.editable_attributes:
            raise KeyError(f"Unknown editable attribute: {name}")
        self.editable_attributes[name].value = value
        self.edited = True
    
    def get(self, name: str) -> Any:
        """Get an attribute value by name (fail fast if missing)."""
        if name not in self.editable_attributes:
            raise KeyError(f"Unknown editable attribute: {name}")
        return self.editable_attributes[name].value


class Condition(EditableMixin, ABC):
    """Editable condition interface for ActivateOnConditionEvent."""
    
    @abstractmethod
    def check(self) -> bool:
        """Return True when the condition is satisfied."""
        ...


class MessageBuilder(EditableMixin, ABC):
    """Editable message builder interface for ActivateOnConditionEvent."""
    
    @abstractmethod
    def build(self) -> Union[None, TelegramMessage, str, List[TelegramMessage]]:
        """Build message content for enqueueing."""
        ...


class FunctionCondition(Condition):
    """Condition wrapper for no-arg callables."""
    
    def __init__(
        self,
        func: Callable[[], Any],
    ) -> None:
        if not callable(func):
            raise TypeError("func must be callable")
        signature = inspect.signature(func)
        if signature.parameters:
            raise ValueError("FunctionCondition requires a no-arg callable")
        self.editable_attributes = []
        self._edited = False
        self._func = func
    
    def check(self) -> bool:
        return bool(self._func())


class FunctionMessageBuilder(MessageBuilder):
    """Message builder wrapper for no-arg callables."""
    
    def __init__(
        self,
        builder: Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
    ) -> None:
        if not callable(builder):
            raise TypeError("builder must be callable")
        signature = inspect.signature(builder)
        if signature.parameters:
            raise ValueError("FunctionMessageBuilder requires a no-arg callable")
        self.editable_attributes = []
        self._edited = False
        self._builder = builder
    
    def build(self) -> Union[None, TelegramMessage, str, List[TelegramMessage]]:
        return self._builder()


class Event:
    """Base class for monitoring events."""
    def __init__(self, event_name: str) -> None:
        self.event_name = event_name

    async def submit(
        self,
        queue: "asyncio.Queue[TelegramMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        """Run the event loop and enqueue TelegramMessage objects."""
        raise NotImplementedError


class ActivateOnConditionEvent(Event, EditableMixin):
    """Poll a condition and enqueue messages when it becomes truthy.
    
    Implements Editable mixin for runtime parameter editing.
    """

    def __init__(
        self,
        event_name: str,
        condition: Condition,
        message_builder: MessageBuilder,
        editable_attributes: Optional[List[EditableAttribute]] = None,
        poll_seconds: float = 5.0,
        fire_when_edited: bool = True,
    ) -> None:
        """Initialize the condition event.
        
        Args:
            event_name: Unique identifier for the event.
            condition: Condition instance to check.
            message_builder: MessageBuilder instance for creating messages.
            editable_attributes: Optional list of editable attributes for the event itself.
            poll_seconds: How often to check the condition.
            fire_when_edited: If True, fire immediately when edited (even if condition is False).
                If False, editing triggers an immediate re-check but only fires if condition is True.
        """
        super().__init__(event_name)
        if condition is None or not isinstance(condition, Condition):
            raise TypeError("condition must be a Condition instance")
        if message_builder is None or not isinstance(message_builder, MessageBuilder):
            raise TypeError("message_builder must be a MessageBuilder instance")
        self.condition = condition
        self.message_builder = message_builder
        self.editable_attributes = editable_attributes or []
        self._edited = False  # Initialize instance-level edited flag
        self.poll_seconds = poll_seconds
        self.fire_when_edited = fire_when_edited

    @property
    def editable_attributes(self) -> dict[str, "EditableAttribute"]:
        """Combined editable attributes from event, condition, and builder.
        
        Returns a dict with:
        - Event's own attributes (no prefix)
        - Condition attributes with 'condition.' prefix
        - Builder attributes with 'builder.' prefix
        """
        combined: dict[str, EditableAttribute] = {}
        # Add event's own attributes
        if hasattr(self, "_editable_attributes"):
            combined.update(self._editable_attributes)
        # Add condition attributes with prefix
        for name, attr in self.condition.editable_attributes.items():
            combined[f"condition.{name}"] = attr
        # Add builder attributes with prefix
        for name, attr in self.message_builder.editable_attributes.items():
            combined[f"builder.{name}"] = attr
        return combined

    @editable_attributes.setter
    def editable_attributes(self, attributes: List["EditableAttribute"]) -> None:
        """Initialize the event's own editable attributes (not condition/builder)."""
        self._init_editable_attributes(attributes)

    def edit(self, name: str, value: Any) -> None:
        """Edit this event or its condition/builder using prefixes."""
        if name.startswith("condition."):
            self.condition.edit(name[len("condition."):], value)
            self.edited = True
            return
        if name.startswith("builder."):
            self.message_builder.edit(name[len("builder."):], value)
            self.edited = True
            return
        if name in self.editable_attributes:
            super().edit(name, value)
            return
        raise KeyError(
            "Unknown editable attribute. Use 'condition.<name>' or 'builder.<name>'."
        )
    
    def get(self, name: str) -> Any:
        """Get an attribute value from event, condition, or builder."""
        if name.startswith("condition."):
            return self.condition.get(name[len("condition."):])
        if name.startswith("builder."):
            return self.message_builder.get(name[len("builder."):])
        if name in self.editable_attributes:
            return super().get(name)
        raise KeyError(
            "Unknown editable attribute. Use 'condition.<name>' or 'builder.<name>'."
        )

    async def submit(
        self,
        queue: "asyncio.Queue[TelegramMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        logger = get_logger()
        logger.info("[%s] event_started poll_seconds=%.1f", self.event_name, self.poll_seconds)
        
        while not stop_event.is_set():
            logger.debug("[%s] checking_condition", self.event_name)
            
            was_edited = self.edited
            if was_edited:
                self.edited = False
            
            condition_result = await asyncio.to_thread(
                self.condition.check,
            )
            
            # Fire if condition is true, or if edited and fire_when_edited is enabled
            should_fire = condition_result or (was_edited and self.fire_when_edited)
            if should_fire:
                message = await _maybe_await(self.message_builder.build)
                if message:
                    logger.info("event_message_queued event_name=%s", self.event_name)
                    await _enqueue_message(queue, message)
                else:
                    logger.warning("[%s] message_builder_returned_none", self.event_name)
            await _wait_or_stop(stop_event, self.poll_seconds)
        
        logger.info("[%s] event_stopped", self.event_name)


class CommandsEvent(Event, UpdatePollerMixin):
    """Listen for Telegram commands and enqueue responses.
    
    Inherits UpdatePollerMixin to use the standardized polling pattern.
    This is a simple router that:
    1. Polls for updates using UpdatePollerMixin.poll()
    2. Handles stale callbacks with "No active session"
    3. Matches "/" commands and delegates to command.run()
    4. Shows help for unknown "/" commands
    5. Ignores non-command messages (no "/" prefix)
    """

    def __init__(
        self,
        event_name: str,
        bot: Bot,
        allowed_chat_id: str,
        commands: List["Command"],
        poll_seconds: float = 2.0,
        initial_offset: Optional[int] = None,
    ) -> None:
        super().__init__(event_name)
        self.bot = bot
        self.allowed_chat_id = str(allowed_chat_id)
        self.commands = commands
        self.poll_seconds = poll_seconds
        self._update_offset: Optional[int] = initial_offset
        self._stop_event: Optional[asyncio.Event] = None
        self._queue: Optional["asyncio.Queue[TelegramMessage]"] = None
        self._current_offset: int = 0

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return self._stop_event.is_set() if self._stop_event else True

    def _get_bot(self) -> Bot:
        return self.bot  # Uses instance attribute

    def _get_chat_id(self) -> str:
        return self.allowed_chat_id  # Uses instance attribute

    def _get_logger(self) -> logging.Logger:
        return get_logger()

    async def handle_callback_update(self, update: Update) -> None:
        """Handle stale callbacks with 'No active session'."""
        logger = self._get_logger()
        logger.debug("stale_callback_received id=%s", update.callback_query.id)
        
        callback_answer = TelegramCallbackAnswerMessage(
            update.callback_query.id,
            text="No active session.",
        )
        await callback_answer.send(self._get_bot(), self._get_chat_id(), logger)
        
        if update.callback_query.message:
            remove_kb = TelegramRemoveKeyboardMessage(update.callback_query.message.message_id)
            await remove_kb.send(self._get_bot(), self._get_chat_id(), logger)

    async def handle_text_update(self, update: Update) -> None:
        """Handle '/' commands, ignore non-commands."""
        text = update.message.text.strip()
        
        if not text.startswith("/"):
            return
        
        command = self._match_command(text)
        if command:
            logger = self._get_logger()
            logger.info("command_matched command=%s", command.command)
            # Consume this update before running command, so it won't see the command as input
            command_offset = update.update_id + 1
            # Command takes over - run it and update offset
            result, self._current_offset = await command.run(self._queue, command_offset)
        else:
            logger = self._get_logger()
            logger.info("unknown_command text=%s", text)
            logger.info("event_message_queued event_name=%s", self.event_name)
            await _enqueue_message(
                self._queue,
                TelegramTextMessage(self._commands_help_text(text)),
            )

    async def submit(
        self,
        queue: "asyncio.Queue[TelegramMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        """Event interface: delegates to poll()."""
        self._queue = queue
        self._stop_event = stop_event
        self._current_offset = self._update_offset or 0
        
        await self.poll(self._current_offset)

    def _match_command(self, text: str) -> Optional["Command"]:
        """Match the first token against known commands."""
        command_token = text.split(maxsplit=1)[0]
        for command in self.commands:
            if command_token == command.command:
                return command
        return None

    def _commands_help_text(self, user_text: str) -> str:
        """Build the unrecognized-command help text listing commands."""
        lines = [
            f"Unknown command: {user_text}",
            "Available commands:",
        ]
        for command in self.commands:
            lines.append(f"{command.command}: {command.description}")
        return "\n".join(lines)


async def _wait_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    """Sleep up to `seconds` but return early if stop_event is set."""
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return


async def _enqueue_message(
    queue: "asyncio.Queue[TelegramMessage]",
    message: Union[None, TelegramMessage, str, List[TelegramMessage]],
) -> None:
    """Queue TelegramMessage instances."""
    if not message:
        return
    if isinstance(message, list):
        messages = message
    elif isinstance(message, TelegramMessage):
        messages = [message]
    else:
        messages = [TelegramTextMessage(str(message))]

    for msg in messages:
        await queue.put(msg)


async def _maybe_await(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Allow both sync and async callables in the same pipeline."""
    result = func(*args, **kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


class Command(ABC):
    """Base class for Telegram commands (async).
    
    Commands run asynchronously until complete. Simple commands complete
    immediately, dialog commands run their own update loop.
    """

    def __init__(self, command: str, description: str) -> None:
        self.command = command
        self.description = description

    @abstractmethod
    async def run(self, queue: asyncio.Queue, update_offset: int = 0) -> Tuple[Any, int]:
        """Run the command until completion.
        
        Args:
            queue: Message queue for sending responses.
            update_offset: Current Telegram update offset to continue from.
            
        Returns:
            Tuple of (result, final_update_offset). Result is command-specific.
        """
        ...


class SimpleCommand(Command):
    """Command that completes immediately by sending a result."""

    def __init__(
        self,
        command: str,
        description: str,
        message_builder: Callable[
            ...,
            Union[None, TelegramMessage, str, List[TelegramMessage]],
        ],
        message_builder_args: tuple[Any, ...] = (),
        message_builder_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(command, description)
        self.message_builder = message_builder
        self.message_builder_args = message_builder_args
        self.message_builder_kwargs = message_builder_kwargs or {}

    async def run(self, queue: asyncio.Queue, update_offset: int = 0) -> Tuple[Any, int]:
        """Execute message builder and enqueue result, then complete."""
        logger = get_logger()
        logger.info("simple_command_executed command=%s", self.command)
        result = self.message_builder(
            *self.message_builder_args,
            **self.message_builder_kwargs,
        )
        logger.info("command_message_queued command=%s", self.command)
        await _enqueue_message(queue, result)
        return None, update_offset  # No result, no updates consumed


class DialogCommand(Command):
    """Command that runs an interactive dialog.
    
    The dialog handles its own update polling via UpdatePollerMixin.
    DialogCommand simply calls dialog.start() and returns the final offset.
    """

    def __init__(
        self,
        command: str,
        description: str,
        dialog: "Dialog",
    ) -> None:
        super().__init__(command, description)
        self.dialog = dialog

    async def run(self, queue: asyncio.Queue, update_offset: int = 0) -> Tuple[Any, int]:
        """Run the dialog until complete.
        
        The dialog handles its own polling via start().
        
        Args:
            queue: Message queue (not used directly, dialog sends via bot).
            update_offset: Current Telegram update offset to continue from.
            
        Returns:
            Tuple of (DialogResult, final_update_offset).
        """
        logger = get_logger()
        logger.info("dialog_command_started command=%s", self.command)
        
        # start() handles reset internally - no need to call reset() explicitly
        result, final_offset = await self.dialog.start({}, update_offset)
        
        logger.info("dialog_command_completed command=%s result=%s", self.command, result)
        return result, final_offset
