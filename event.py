"""Event system for the bot framework."""

import asyncio
import inspect
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Coroutine, List, Optional, Union

from telegram import Update

from .telegram_utilities import (
    TelegramMessage,
    TelegramTextMessage,
    TelegramCallbackAnswerMessage,
    TelegramRemoveKeyboardMessage,
)
from .accessors import get_app, get_logger
from .polling import UpdatePollerMixin, set_next_update_id
from .editable import EditableAttribute, EditableMixin

if TYPE_CHECKING:
    from .dialog import Dialog, DialogResponse

MINIMAL_TIME_BETWEEN_MESSAGES = 5.0 / 60.0


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

    _func: Callable[[], Any]

    def __init__(self, func: Callable[[], Any]) -> None:
        """Initialize a function-based condition.

        Args:
            func: No-argument callable that returns a truthy/falsy value.
                The result is converted to bool via bool(func()).

        Raises:
            TypeError: If func is not callable.
            ValueError: If func has any parameters.
        """
        if not callable(func):
            raise TypeError("func must be callable")
        signature = inspect.signature(func)
        if signature.parameters:
            raise ValueError("FunctionCondition requires a no-arg callable")
        self.editable_attributes = []
        self._func = func

    def check(self) -> bool:
        """Check if the condition is satisfied."""
        return bool(self._func())


class FunctionMessageBuilder(MessageBuilder):
    """Message builder wrapper for no-arg callables."""

    _builder: Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]]

    def __init__(
        self,
        builder: Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
    ) -> None:
        """Initialize a function-based message builder.

        Args:
            builder: No-argument callable that returns a message or None.
                Can return str, TelegramMessage, List[TelegramMessage], or None.

        Raises:
            TypeError: If builder is not callable.
            ValueError: If builder has any parameters.
        """
        if not callable(builder):
            raise TypeError("builder must be callable")
        signature = inspect.signature(builder)
        if signature.parameters:
            raise ValueError("FunctionMessageBuilder requires a no-arg callable")
        self.editable_attributes = []
        self._builder = builder

    def build(self) -> Union[None, TelegramMessage, str, List[TelegramMessage]]:
        """Build the message content."""
        return self._builder()


class Event:
    """Base class for monitoring events."""

    event_name: str

    def __init__(self, event_name: str) -> None:
        self.event_name = event_name

    async def submit(self, stop_event: asyncio.Event) -> None:
        """Run the event loop until stop_event is set."""
        raise NotImplementedError


class ActivateOnConditionEvent(Event, EditableMixin):
    """Poll a condition and enqueue messages when it becomes truthy.

    Implements Editable mixin for runtime parameter editing.
    """

    condition: Condition
    message_builder: MessageBuilder
    poll_seconds: float
    fire_when_edited: bool
    _editable_attributes: dict[str, "EditableAttribute"]

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

    async def submit(self, stop_event: asyncio.Event) -> None:
        logger = get_logger()
        logger.info("ActivateOnConditionEvent.submit: started event=%s poll_seconds=%.1f", self.event_name, self.poll_seconds)

        while not stop_event.is_set():
            logger.debug("ActivateOnConditionEvent.submit: checking_condition event=%s", self.event_name)

            was_edited = self.edited
            if was_edited:
                self.edited = False

            condition_result = await asyncio.to_thread(self.condition.check)

            # Fire if condition is true, or if edited and fire_when_edited is enabled
            should_fire = condition_result or (was_edited and self.fire_when_edited)
            if should_fire:
                message = await _maybe_await(self.message_builder.build)
                if message:
                    logger.info("ActivateOnConditionEvent.submit: message_queued event=%s", self.event_name)
                    await get_app().send_messages(message)
                else:
                    logger.warning("ActivateOnConditionEvent.submit: message_builder_returned_none event=%s", self.event_name)
            await _wait_or_stop(stop_event, self.poll_seconds)

        logger.info("ActivateOnConditionEvent.submit: stopped event=%s", self.event_name)


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

    commands: List["Command"]
    poll_seconds: float
    _stop_event: Optional[asyncio.Event]

    def __init__(
        self,
        event_name: str,
        commands: List["Command"],
        poll_seconds: float = 2.0,
    ) -> None:
        super().__init__(event_name)
        self.commands = commands
        self.poll_seconds = poll_seconds
        self._stop_event = None

    # UpdatePollerMixin abstract methods
    def should_stop_polling(self) -> bool:
        return self._stop_event.is_set() if self._stop_event else True

    async def handle_callback_update(self, update: Update) -> None:
        """Handle stale callbacks with 'No active session'."""
        logger = get_logger()
        callback_query = update.callback_query
        if callback_query is None:
            return
        logger.debug("CommandsEvent.handle_callback_update: stale_callback id=%s", callback_query.id)

        await get_app().send_messages(TelegramCallbackAnswerMessage(
            callback_query.id,
            text="No active session.",
        ))

        if callback_query.message:
            await get_app().send_messages(
                TelegramRemoveKeyboardMessage(callback_query.message.message_id)
            )

    async def handle_text_update(self, update: Update) -> None:
        """Handle '/' commands, ignore non-commands."""
        if update.message is None or update.message.text is None:
            return
        text = update.message.text.strip()

        if not text.startswith("/"):
            return

        command = self._match_command(text)
        logger = get_logger()
        if command:
            logger.info("CommandsEvent.handle_text_update: matched command=%s", command.command)
            # Set offset past this command before running, so command won't see itself as input
            set_next_update_id(update.update_id + 1)
            await command.run()
        else:
            logger.info("CommandsEvent.handle_text_update: unknown_command text=%s", text)
            await get_app().send_messages(
                TelegramTextMessage(self._commands_help_text(text)),
            )

    async def submit(self, stop_event: asyncio.Event) -> None:
        """Event interface: delegates to poll()."""
        self._stop_event = stop_event
        await self.poll()

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


async def _maybe_await(
    func: Union[Callable[..., Any], Callable[..., Coroutine[Any, Any, Any]]],
    *args: Any,
    **kwargs: Any,
) -> Any:
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

    command: str
    description: str

    def __init__(self, command: str, description: str) -> None:
        self.command = command
        self.description = description

    @abstractmethod
    async def run(self) -> Any:
        """Run the command until completion.

        Returns:
            Result (command-specific, or None).
        """
        ...


class SimpleCommand(Command):
    """Command that completes immediately by sending a result.

    The message_builder must be a callable that takes no arguments and returns
    a message (str, TelegramMessage, list of messages, or None).
    """

    message_builder: Union[
        Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
        Callable[[], Coroutine[Any, Any, Union[None, TelegramMessage, str, List[TelegramMessage]]]],
    ]

    def __init__(
        self,
        command: str,
        description: str,
        message_builder: Union[
            Callable[[], Union[None, TelegramMessage, str, List[TelegramMessage]]],
            Callable[[], Coroutine[Any, Any, Union[None, TelegramMessage, str, List[TelegramMessage]]]],
        ],
    ) -> None:
        super().__init__(command, description)
        self.message_builder = message_builder

    async def run(self) -> Any:
        """Execute message builder and send result, then complete."""
        logger = get_logger()
        logger.info("SimpleCommand.run: executed command=%s", self.command)
        result = await _maybe_await(self.message_builder)
        if result:
            logger.debug("SimpleCommand.run: sending message command=%s", self.command)
            await get_app().send_messages(result)
            logger.info("SimpleCommand.run: sent command=%s", self.command)
        return None


class DialogCommand(Command):
    """Command that runs an interactive dialog.

    The dialog handles its own update polling via UpdatePollerMixin.
    DialogCommand simply calls dialog.start() and returns the final offset.
    """

    dialog: "Dialog"

    def __init__(
        self,
        command: str,
        description: str,
        dialog: "Dialog",
    ) -> None:
        super().__init__(command, description)
        self.dialog = dialog

    async def run(self) -> Any:
        """Run the dialog until complete.

        The dialog handles its own polling via start().

        Returns:
            DialogResult.
        """
        logger = get_logger()
        logger.info("DialogCommand.run: started command=%s", self.command)
        # start() handles reset internally - no need to call reset() explicitly
        result = await self.dialog.start({})
        logger.info("DialogCommand.run: completed command=%s result=%s", self.command, result)
        return result
