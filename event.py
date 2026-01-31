"""Event system for the bot framework."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
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
from .bot_application import get_bot, get_chat_id, get_logger

if TYPE_CHECKING:
    from .dialog import Dialog, DialogResponse

MINIMAL_TIME_BETWEEN_MESSAGES = 5.0 / 60.0


async def flush_pending_updates(bot: Bot) -> int:
    """Flush all pending updates and return the next offset.
    
    Call this when the bot starts to ignore old messages and only
    process messages sent after startup.
    
    Args:
        bot: The Telegram Bot instance.
        
    Returns:
        The update offset to use for subsequent polling.
    """
    logger = get_logger()
    
    # Use offset=-1 to get the latest update and mark all as read
    updates = await bot.get_updates(offset=-1, timeout=0)
    
    if updates:
        # Return offset after the latest update
        new_offset = updates[-1].update_id + 1
        logger.info("flush_pending_updates cleared=%d next_offset=%d", len(updates), new_offset)
        return new_offset
    
    # No pending updates, start from 0
    logger.info("flush_pending_updates no_pending_updates")
    return 0


async def poll_updates(
    bot: Bot,
    allowed_chat_id: str,
    update_offset: int,
    timeout: int = 5,
) -> Tuple[List[Update], int]:
    """Poll for updates and return (updates, new_offset)."""
    updates = await bot.get_updates(
        offset=update_offset,
        timeout=timeout,
        allowed_updates=["message", "callback_query"],
    )
    new_offset = update_offset
    for update in updates:
        new_offset = update.update_id + 1
    if updates:
        logger = get_logger()
        logger.debug("poll_updates_received count=%d", len(updates))
    return updates, new_offset


def get_chat_id_from_update(update: Update) -> Optional[int]:
    """Extract chat_id from update."""
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat_id
    if update.message:
        return update.message.chat_id
    return None


@dataclass
class EventMessage:
    """Payload for a single user-facing message.

    message_title is used as the Telegram title, while message_body contains
    the formatted content (HTML in this project).
    """
    message_title: str
    message_body: TelegramMessage


class EditableField:
    """A field that can be edited at runtime with string parsing and validation.
    
    - `parse`: User-provided callable that receives string, returns typed value
    - `value` property: getter returns typed value, setter parses strings and validates
    - `validator`: Optional function that receives typed value, returns (is_valid, error_msg)
    
    Field values are passed to message builders via kwargs, which update their
    internal state using CallUpdatesInternalState.
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


class Editable(ABC):
    """Mixin for objects with runtime-editable parameters.
    
    The `edited` property allows signaling that parameters have changed,
    triggering immediate re-processing in events that support it.
    """
    
    _edited: bool = False

    @property
    @abstractmethod
    def editable_name(self) -> str:
        """Human-readable name for display."""
        ...

    @property
    @abstractmethod
    def editable_fields(self) -> List["EditableField"]:
        """List of editable fields."""
        ...

    @property
    def edited(self) -> bool:
        """Check if the object has been marked as edited."""
        return self._edited

    @edited.setter
    def edited(self, value: bool) -> None:
        """Set the edited flag."""
        logger = get_logger()
        logger.info("[%s] edited_flag_set value=%s", self.editable_name, value)
        self._edited = value

    def get_editable_kwargs(self) -> dict:
        """Build dict from editable fields for merging with kwargs."""
        return {field.name: field.value for field in self.editable_fields}


class Event:
    """Base class for monitoring events."""
    def __init__(self, title: str) -> None:
        self.title = title

    async def submit(
        self,
        queue: "asyncio.Queue[EventMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        """Run the event loop and enqueue EventMessage objects."""
        raise NotImplementedError


class TimeEvent(Event):
    """Emit a message periodically using a provided message_builder."""
    def __init__(
        self,
        title: str,
        interval_hours: float,
        message_builder: Callable[
            [...],
            Union[None, EventMessage, TelegramMessage, str, List[EventMessage]],
        ],
        message_builder_args: tuple[Any, ...] = (),
        message_builder_kwargs: Optional[dict[str, Any]] = None,
        fire_on_first_check: bool = False,
    ) -> None:
        """Initialize the time-based event.

        interval_hours controls the minimum delay between emissions. If
        fire_on_first_check is True, the first check can emit immediately.
        """
        super().__init__(title)
        assert (
            interval_hours >= MINIMAL_TIME_BETWEEN_MESSAGES
        ), "interval_hours must be at least 5 minutes"
        self.interval_hours = max(interval_hours, 0.0)
        self.message_builder = message_builder
        self.message_builder_args = message_builder_args
        self.message_builder_kwargs = message_builder_kwargs or {}
        self.fire_on_first_check = fire_on_first_check

    async def submit(
        self,
        queue: "asyncio.Queue[EventMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        """Run the interval gating and enqueue messages when due."""
        interval_seconds = self.interval_hours * 3600.0
        if self.fire_on_first_check and not stop_event.is_set():
            await self._enqueue_message(queue)

        while not stop_event.is_set():
            # Sleep in a cancel-friendly way; honors stop_event.
            await _wait_or_stop(stop_event, max(interval_seconds, 0.1))
            if stop_event.is_set():
                break
            await self._enqueue_message(queue)

    async def _enqueue_message(
        self,
        queue: "asyncio.Queue[EventMessage]",
    ) -> None:
        """Normalize message builder output to EventMessage and enqueue."""
        message = self.message_builder(*self.message_builder_args, **self.message_builder_kwargs)
        await _enqueue_from_message(queue, self.title, message)


class ActivateOnConditionEvent(Event, Editable):
    """Poll a condition and enqueue messages when it becomes truthy.
    
    Implements Editable mixin for runtime parameter editing.
    """

    def __init__(
        self,
        title: str,
        condition_func: Callable[..., Any],
        condition_args: tuple[Any, ...] = (),
        condition_kwargs: Optional[dict[str, Any]] = None,
        message_builder: Callable[..., Union[None, EventMessage, TelegramMessage, str, List[EventMessage]]] = None,
        message_builder_args: tuple[Any, ...] = (),
        message_builder_kwargs: Optional[dict[str, Any]] = None,
        editable_fields: Optional[List[EditableField]] = None,
        poll_seconds: float = 5.0,
    ) -> None:
        super().__init__(title)
        self.condition_func = condition_func
        self.condition_args = condition_args
        self.condition_kwargs = condition_kwargs or {}
        self.message_builder = message_builder
        self.message_builder_args = message_builder_args
        self._base_kwargs = message_builder_kwargs or {}
        self._editable_fields = editable_fields or []
        self._edited = False  # Initialize instance-level edited flag
        self.poll_seconds = poll_seconds

    @property
    def editable_name(self) -> str:
        """Human-readable name for display."""
        return self.title

    @property
    def editable_fields(self) -> List[EditableField]:
        """List of editable fields."""
        return self._editable_fields

    def _get_message_builder_kwargs(self) -> dict:
        """Get kwargs by merging base kwargs with editable field values.
        
        Editable field values are passed to the message builder's __call__.
        Builders using CallUpdatesInternalState will update their internal
        state from these kwargs before execution.
        """
        editable_dict = self.get_editable_kwargs()
        return {**self._base_kwargs, **editable_dict}

    async def submit(
        self,
        queue: "asyncio.Queue[EventMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        logger = get_logger()
        logger.info("[%s] event_started poll_seconds=%.1f", self.title, self.poll_seconds)
        
        while not stop_event.is_set():
            logger.debug("[%s] checking_condition", self.title)
            
            was_edited = self.edited
            if was_edited:
                self.edited = False
            
            condition_result = await asyncio.to_thread(
                self.condition_func,
                *self.condition_args,
                **self.condition_kwargs,
            )
            if condition_result or was_edited:
                if self.message_builder is None:
                    logger.error("[%s] missing_message_builder", self.title)
                else:
                    # Use merged kwargs (base + editable values)
                    merged_kwargs = self._get_message_builder_kwargs()
                    logger.debug("[%s] building_message kwargs=%s", self.title, merged_kwargs)
                    message = await _maybe_await(
                        self.message_builder,
                        *self.message_builder_args,
                        **merged_kwargs,
                    )
                    if message:
                        logger.info("[%s] message_built_successfully", self.title)
                        await _enqueue_from_message(queue, self.title, message)
                    else:
                        logger.warning("[%s] message_builder_returned_none", self.title)
            await _wait_or_stop(stop_event, self.poll_seconds)
        
        logger.info("[%s] event_stopped", self.title)


class TelegramCommandsEvent(Event):
    """Listen for Telegram commands and enqueue responses.
    
    This is a simple router that:
    1. Polls for updates and matches "/" commands
    2. Awaits command.run() which blocks until the command completes
    3. Shows help for unknown "/" commands
    4. Ignores non-command messages (no "/" prefix)
    """

    def __init__(
        self,
        title: str,
        bot: Bot,
        allowed_chat_id: str,
        commands: List["Command"],
        poll_seconds: float = 2.0,
        initial_offset: Optional[int] = None,
    ) -> None:
        super().__init__(title)
        self.bot = bot
        self.allowed_chat_id = str(allowed_chat_id)
        self.commands = commands
        self.poll_seconds = poll_seconds
        self._update_offset: Optional[int] = initial_offset

    async def submit(
        self,
        queue: "asyncio.Queue[EventMessage]",
        stop_event: asyncio.Event,
    ) -> None:
        """Poll Telegram updates and route commands."""
        logger = get_logger()
        while not stop_event.is_set():
            try:
                updates, new_offset = await poll_updates(
                    self.bot,
                    self.allowed_chat_id,
                    self._update_offset or 0,
                )
                self._update_offset = new_offset
            except Exception as exc:
                logger.error("command_poll_failed error=%s", exc)
                await _wait_or_stop(stop_event, self.poll_seconds)
                continue

            for update in updates:
                chat_id = get_chat_id_from_update(update)
                if chat_id is None or str(chat_id) != self.allowed_chat_id:
                    continue

                # Handle stale callbacks when no command is running
                if update.callback_query:
                    logger.debug("stale_callback_received id=%s", update.callback_query.id)
                    callback_answer = TelegramCallbackAnswerMessage(
                        update.callback_query.id,
                        text="No active session.",
                    )
                    await callback_answer.send(self.bot, self.allowed_chat_id, "callback", logger)
                    
                    # Remove keyboard from stale message
                    if update.callback_query.message:
                        clicked_msg_id = update.callback_query.message.message_id
                        remove_kb = TelegramRemoveKeyboardMessage(clicked_msg_id)
                        await remove_kb.send(self.bot, self.allowed_chat_id, "callback", logger)
                    continue

                if not update.message or not update.message.text:
                    continue

                text = update.message.text.strip()

                # Only process commands (starting with "/")
                if not text.startswith("/"):
                    continue

                command = self._match_command(text)
                if command:
                    # Await command.run() - blocks until command completes
                    # DialogCommand fully takes over update listening
                    logger.info("command_matched command=%s", command.command)
                    self._update_offset = await command.run(queue, self._update_offset)
                else:
                    logger.info("unknown_command text=%s", text)
                    await _enqueue_from_message(
                        queue,
                        self.title,
                        TelegramTextMessage(self._commands_help_text(text)),
                    )

            await _wait_or_stop(stop_event, self.poll_seconds)

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


async def _enqueue_from_message(
    queue: "asyncio.Queue[EventMessage]",
    title: str,
    message: Union[None, EventMessage, TelegramMessage, str, List[EventMessage]],
) -> None:
    """Normalize a message-like object into EventMessage instances and put into the queue."""
    if not message:
        return
    if isinstance(message, list):
        messages: List[EventMessage] = message
    elif isinstance(message, EventMessage):
        messages = [message]
    elif isinstance(message, TelegramMessage):
        messages = [EventMessage(message_title=title, message_body=message)]
    else:
        messages = [
            EventMessage(
                message_title=title,
                message_body=TelegramTextMessage(str(message)),
            )
        ]

    for event_message in messages:
        await queue.put(event_message)


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
    async def run(self, queue: asyncio.Queue, update_offset: int = 0) -> int:
        """Run the command until completion.
        
        Args:
            queue: Message queue for sending responses.
            update_offset: Current Telegram update offset to continue from.
            
        Returns:
            The final update_offset after the command completes.
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
            Union[None, EventMessage, TelegramMessage, str, List[EventMessage]],
        ],
        message_builder_args: tuple[Any, ...] = (),
        message_builder_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(command, description)
        self.message_builder = message_builder
        self.message_builder_args = message_builder_args
        self.message_builder_kwargs = message_builder_kwargs or {}

    async def run(self, queue: asyncio.Queue, update_offset: int = 0) -> int:
        """Execute message builder and enqueue result, then complete."""
        logger = get_logger()
        logger.info("simple_command_executed command=%s", self.command)
        result = self.message_builder(
            *self.message_builder_args,
            **self.message_builder_kwargs,
        )
        await _enqueue_from_message(queue, "command", result)
        return update_offset  # No updates consumed, return same offset


class DialogCommand(Command):
    """Command that runs an interactive dialog with its own update loop."""

    def __init__(
        self,
        command: str,
        description: str,
        dialog: "Dialog",
    ) -> None:
        super().__init__(command, description)
        self.dialog = dialog

    async def run(self, queue: asyncio.Queue, update_offset: int = 0) -> int:
        """Run dialog's update loop until dialog completes.
        
        The dialog fully owns the conversation - TelegramCommandsEvent stops
        listening while this runs. All updates are handled here.
        
        Args:
            queue: Message queue (not used directly, dialog sends via bot).
            update_offset: Current Telegram update offset to continue from.
            
        Returns:
            The final update_offset after the dialog completes.
        """
        logger = get_logger()
        bot = get_bot()
        chat_id = get_chat_id()
        
        logger.info("dialog_command_started command=%s", self.command)

        # Reset dialog to ensure fresh state
        self.dialog.reset()

        # Send initial message with keyboard (passing empty context)
        response = self.dialog.start({})
        last_message_id = await self._send_response(response, bot, chat_id, logger, None)

        # Dialog fully takes over update listening from TelegramCommandsEvent
        current_offset = update_offset
        while not self.dialog.is_complete:
            updates, current_offset = await poll_updates(
                bot, chat_id, current_offset
            )

            for update in updates:
                update_chat_id = get_chat_id_from_update(update)
                if update_chat_id is None or str(update_chat_id) != chat_id:
                    logger.debug("dialog_ignoring_update_wrong_chat update_id=%d", update.update_id)
                    continue

                if update.callback_query:
                    # Answer callback using TelegramCallbackAnswerMessage
                    callback_answer = TelegramCallbackAnswerMessage(update.callback_query.id)
                    await callback_answer.send(bot, chat_id, "callback", logger)
                    
                    # Remove keyboard from clicked message to prevent stale clicks
                    if update.callback_query.message:
                        clicked_msg_id = update.callback_query.message.message_id
                        remove_kb = TelegramRemoveKeyboardMessage(clicked_msg_id)
                        await remove_kb.send(bot, chat_id, "dialog", logger)

                    callback_data = update.callback_query.data
                    response = self.dialog.handle_callback(callback_data)
                    
                    if response is None:
                        # Unexpected callback - send warning
                        logger.warning("dialog_unexpected_callback data=%s", callback_data)
                        warning_msg = TelegramTextMessage("Unexpected button press. Please try again.")
                        await warning_msg.send(bot, chat_id, "dialog", logger)
                        continue
                    
                    last_message_id = await self._send_response(response, bot, chat_id, logger, last_message_id)

                elif update.message and update.message.text:
                    user_text = update.message.text.strip()
                    response = self.dialog.handle_text_input(user_text)
                    
                    if response is None:
                        # Dialog doesn't accept text - send clarifying message
                        if self.dialog.is_active:
                            logger.info("dialog_unexpected_text_input text=%s", user_text[:50])
                            clarify_msg = TelegramTextMessage(
                                "Please use the buttons to make a selection."
                            )
                            await clarify_msg.send(bot, chat_id, "dialog", logger)
                        continue
                    
                    last_message_id = await self._send_response(response, bot, chat_id, logger, last_message_id)
                
                elif update.message:
                    # Non-text message (photo, sticker, etc.) - warn user
                    logger.info("dialog_unexpected_message_type update_id=%d", update.update_id)
                    warning_msg = TelegramTextMessage(
                        "Please use the buttons or type a text response."
                    )
                    await warning_msg.send(bot, chat_id, "dialog", logger)

        logger.info("dialog_command_completed command=%s value=%s", self.command, self.dialog.value)
        return current_offset  # Return final offset for TelegramCommandsEvent to continue

    async def _send_response(
        self,
        response: "DialogResponse",
        bot: "Bot",
        chat_id: str,
        logger: "logging.Logger",
        last_message_id: Optional[int],
    ) -> Optional[int]:
        """Send a dialog response and return the new message ID if applicable."""
        from .dialog import DialogResponse
        
        # Check for NO_CHANGE sentinel
        if response is DialogResponse.NO_CHANGE or not response.text:
            return last_message_id
        
        if response.edit_message and last_message_id:
            # Edit existing message
            edit_msg = TelegramEditMessage(last_message_id, response.text, response.keyboard)
            await edit_msg.send(bot, chat_id, "dialog", logger)
            return last_message_id
        
        # Send new message
        if response.keyboard:
            options_msg = TelegramOptionsMessage(response.text, response.keyboard)
            await options_msg.send(bot, chat_id, "dialog", logger)
            if options_msg.sent_message:
                return options_msg.sent_message.message_id
        else:
            text_msg = TelegramTextMessage(response.text)
            await text_msg.send(bot, chat_id, "dialog", logger)
        
        return last_message_id
