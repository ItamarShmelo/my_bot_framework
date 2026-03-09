"""BotApplication singleton for managing Telegram bot lifecycle."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram import Bot

from .accessors import _set_instance
from .event import Command, Event, SimpleCommand, CommandsEvent
from .polling import flush_pending_updates
from .telegram_utilities import TelegramMessage, TelegramTextMessage


class BotApplication:
    """Singleton class managing the Telegram bot application.

    Encapsulates the bot instance, events, and commands.
    Provides built-in /terminate and /commands functionality.
    Supports dynamic event registration and removal while the bot is running.

    Usage:
        app = BotApplication.initialize(
            token="YOUR_BOT_TOKEN",
            chat_id="YOUR_CHAT_ID",
            logger=your_logger,
        )
        app.register_event(my_event)
        app.remove_event("my_event_name")
        app.register_command(my_command)
        await app.run()

    Event names must be unique within the application. Registering a duplicate
    name raises ValueError, and removing a missing event name raises KeyError.
    """

    _instance: BotApplication | None = None

    bot: Bot
    chat_id: str
    logger: logging.Logger
    stop_event: asyncio.Event
    events: list[Event]
    commands: list[Command]
    _running: bool
    _events_by_name: dict[str, Event]
    _event_tasks: dict[str, asyncio.Task[None]]
    _task_event_names: dict[asyncio.Task[None], str]
    _removed_event_names: set[str]
    _new_event_signal: asyncio.Event

    def __init__(
        self,
        bot: Bot,
        chat_id: str,
        logger: logging.Logger,
    ) -> None:
        """Private constructor - use initialize() instead."""
        self.bot = bot
        self.chat_id = chat_id
        self.logger = logger
        self.stop_event = asyncio.Event()
        self.events = []
        self._events_by_name = {}
        self.commands = []
        self._running = False
        self._event_tasks = {}
        self._task_event_names = {}
        self._removed_event_names = set()
        self._new_event_signal = asyncio.Event()

    @classmethod
    def get_instance(cls) -> BotApplication:
        """Get the singleton instance.

        Raises:
            RuntimeError: If initialize() hasn't been called.
        """
        if cls._instance is None:
            logging.getLogger(__name__).critical(
                "BotApplication.get_instance: not_initialized",
            )
            raise RuntimeError(
                "BotApplication not initialized. Call BotApplication.initialize() first."
            )
        return cls._instance

    @classmethod
    def initialize(
        cls,
        token: str,
        chat_id: str,
        logger: logging.Logger,
    ) -> BotApplication:
        """Initialize the singleton with required parameters.

        Args:
            token: Telegram bot token.
            chat_id: Allowed chat ID for receiving/sending messages.
            logger: Logger instance for the application.

        Returns:
            The initialized BotApplication singleton.
        """
        if cls._instance is not None:
            logger.warning("BotApplication.initialize: already_initialized, returning existing")
            return cls._instance

        bot = Bot(token=token)
        cls._instance = cls(bot, chat_id, logger)
        _set_instance(cls._instance)  # Set the accessor singleton
        logger.info("BotApplication.initialize: initialized chat_id=%s", chat_id)
        return cls._instance

    def register_event(self, event: Event) -> None:
        """Register an event to be run by the bot.

        If the bot is already running, the event is started immediately.
        Otherwise it will be started when run() is called.

        Args:
            event: Event instance to register.

        Raises:
            ValueError: If another event with the same name is already
                registered or still shutting down.
        """
        self._register_event_instance(event)
        if self._running:
            self._start_event_task(event)
            self._new_event_signal.set()
            self.logger.info(
                "BotApplication.register_event: started_mid_run event_name=%s",
                event.event_name,
            )
        else:
            self.logger.debug(
                "BotApplication.register_event: registered event_name=%s",
                event.event_name,
            )

    def remove_event(self, event_name: str) -> None:
        """Remove a previously registered event by name.

        If the bot is running, the event task is cancelled and the supervisor
        loop treats the resulting cancellation as intentional.

        Args:
            event_name: Unique name of the event to remove.

        Raises:
            KeyError: If no event with that name is registered.
        """
        if event_name not in self._events_by_name:
            self.logger.warning(
                "BotApplication.remove_event: missing event_name=%s running=%s",
                event_name,
                self._running,
            )
            raise KeyError(f"No event registered with name '{event_name}'.")

        self.logger.debug(
            "BotApplication.remove_event: unregistering event_name=%s running=%s",
            event_name,
            self._running,
        )
        self._unregister_event_name(event_name)

        if self._running:
            task = self._event_tasks.get(event_name)
            if task is not None:
                self._removed_event_names.add(event_name)
                self.logger.debug(
                    "BotApplication.remove_event: cancelling_task event_name=%s task_done=%s",
                    event_name,
                    task.done(),
                )
                if not task.done():
                    task.cancel()
                self._new_event_signal.set()
                self.logger.info(
                    "BotApplication.remove_event: removed_running event_name=%s",
                    event_name,
                )
                return

            self.logger.info(
                "BotApplication.remove_event: removed_running_without_task event_name=%s",
                event_name,
            )
            return

        self.logger.info(
            "BotApplication.remove_event: removed event_name=%s",
            event_name,
        )

    def register_command(self, command: Command) -> None:
        """Register a command to be available to users."""
        self.commands.append(command)
        self.logger.debug("BotApplication.register_command: registered command=%s", command.command)

    async def terminate(self) -> None:
        """Built-in terminate handler - sends goodbye and sets stop_event."""
        self.logger.info("BotApplication.terminate: requested")
        await self.send_messages("Bot terminating. Goodbye!")
        self.stop_event.set()

    def list_commands(self) -> str:
        """Built-in commands list handler - returns formatted list of all commands."""
        lines = [f"{cmd.command}: {cmd.description}" for cmd in self.commands]
        lines.append("/terminate: Terminate the bot and shut down. (can be invoked anytime)")
        return "\n".join(lines)

    async def run(self, skip_commands: bool = False) -> int:
        """Run the bot application.

        Registers built-in commands, initializes the HTTP session, then
        enters the event loop. Blocks until stop_event is set or a fatal
        error terminates the bot.

        Args:
            skip_commands: If True, skip registering the CommandsEvent
                (commands will not be polled from Telegram).

        Returns:
            Exit code (0 for success).
        """
        self._register_commands(skip_commands=skip_commands)
        self.logger.info(
            "BotApplication.run: starting events=%d commands=%d skip_commands=%s",
            len(self.events),
            len(self.commands),
            skip_commands,
        )
        await self._initialize_http_session()
        return await self._run_event_loop()

    def _register_commands(self, skip_commands: bool = False) -> None:
        """Register /commands and optionally the CommandsEvent.

        Args:
            skip_commands: If True, skip registering the CommandsEvent.
        """
        self.logger.debug(
            "BotApplication._register_commands: registering built-in commands skip_commands=%s",
            skip_commands,
        )
        if not any(command.command == "/commands" for command in self.commands):
            self.commands.append(
                SimpleCommand(
                    command="/commands",
                    description="List all available commands.",
                    message_builder=self.list_commands,
                )
            )
        if not skip_commands:
            existing_event = self._events_by_name.get("commands")
            if existing_event is not None:
                if not isinstance(existing_event, CommandsEvent):
                    raise ValueError(
                        "Event name 'commands' is reserved for the built-in CommandsEvent."
                    )
                self.logger.debug(
                    "BotApplication._register_commands: CommandsEvent already_registered",
                )
                return

            commands_event = CommandsEvent(
                event_name="commands",
                commands=self.commands,
            )
            self._register_event_instance(commands_event)
            self.logger.debug(
                "BotApplication._register_commands: registered CommandsEvent "
                "event_name=%s commands_count=%d",
                commands_event.event_name,
                len(self.commands),
            )
        else:
            self.logger.info(
                "BotApplication._register_commands: skipped CommandsEvent "
                "registration skip_commands=True",
            )

    async def _initialize_http_session(self) -> None:
        """Initialize the Telegram bot's HTTP session.

        Raises:
            Exception: If the HTTP session cannot be initialized.
        """
        try:
            self.logger.debug("BotApplication._initialize_http_session: initializing")
            await self.bot.initialize()
            self.logger.debug("BotApplication._initialize_http_session: initialized")
        except Exception:
            self.logger.critical(
                "BotApplication._initialize_http_session: failed",
                exc_info=True,
            )
            raise

    async def _run_event_loop(self) -> int:
        """Supervisor loop: start event tasks and watch for new ones mid-run.

        Detects task failures so that fatal exceptions (e.g. BadRequest from
        invalid HTML, unexpected condition/builder crashes) propagate and
        terminate the bot instead of being silently swallowed.  Events
        registered via register_event() while the loop is running are picked
        up automatically on the next iteration.

        Returns:
            Exit code (0 for success).
        """
        try:
            await flush_pending_updates(self.bot)

            self._running = True
            self._event_tasks = {}
            self._task_event_names = {}
            self._removed_event_names.clear()
            self._new_event_signal.clear()
            for event in self.events:
                self._start_event_task(event)

            self.logger.info(
                "BotApplication._run_event_loop: started events=%d commands=%d",
                len(self.events),
                len(self.commands),
            )

            stop_task: asyncio.Task[bool] = asyncio.create_task(self.stop_event.wait())

            while not self.stop_event.is_set():
                # Wait for either stop signal, new event registration, or task completion
                signal_task: asyncio.Task[bool] = asyncio.create_task(
                    self._new_event_signal.wait(),
                )

                wait_tasks: set[asyncio.Task[Any]] = set(self._event_tasks.values())
                wait_tasks.update({stop_task, signal_task})
                done, _ = await asyncio.wait(
                    wait_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if signal_task in done:
                    self._new_event_signal.clear()
                else:
                    signal_task.cancel()

                for task in done:
                    if task is stop_task or task is signal_task:
                        continue
                    self._handle_event_task_completion(task)

                if stop_task in done:
                    break

            # Normal shutdown: cancel remaining event tasks
            for task in self._event_tasks.values():
                task.cancel()
            if not stop_task.done():
                stop_task.cancel()
            await asyncio.gather(
                *self._event_tasks.values(), stop_task, return_exceptions=True,
            )
            self._event_tasks.clear()
            self._task_event_names.clear()
            self._removed_event_names.clear()

            self.logger.info("BotApplication._run_event_loop: stopped")
            return 0
        except Exception as exc:
            self.logger.critical(
                "BotApplication._run_event_loop: fatal error_type=%s",
                type(exc).__name__,
                exc_info=True,
            )
            error_text = f"Fatal error: {type(exc).__name__}: {exc}"
            await self.send_messages(TelegramTextMessage(error_text))
            raise
        finally:
            self._running = False
            try:
                self.logger.debug("BotApplication._run_event_loop: shutting down HTTP session")
                await self.bot.shutdown()
                self.logger.debug("BotApplication._run_event_loop: HTTP session shut down")
            except Exception:
                self.logger.critical(
                    "BotApplication._run_event_loop: http_session_shutdown_failed",
                    exc_info=True,
                )

    def _register_event_instance(self, event: Event) -> None:
        """Register an event object in the internal registries.

        Args:
            event: Event instance to register.

        Raises:
            ValueError: If the event name is already registered or still
                shutting down from a prior removal.
        """
        self._ensure_event_name_available(event.event_name)
        self.events.append(event)
        self._events_by_name[event.event_name] = event
        self.logger.debug(
            "BotApplication._register_event_instance: tracked event_name=%s registered_events=%d",
            event.event_name,
            len(self.events),
        )

    def _unregister_event_name(self, event_name: str) -> None:
        """Remove an event from the registration registries.

        Args:
            event_name: Unique event name to unregister.
        """
        event = self._events_by_name.pop(event_name)
        self.events[:] = [
            registered_event
            for registered_event in self.events
            if registered_event is not event
        ]
        self.logger.debug(
            "BotApplication._unregister_event_name: untracked event_name=%s registered_events=%d",
            event_name,
            len(self.events),
        )

    def _ensure_event_name_available(self, event_name: str) -> None:
        """Ensure an event name is not already in use.

        Args:
            event_name: Candidate unique event name.

        Raises:
            ValueError: If the name is already registered or still shutting
                down from a prior removal.
        """
        if event_name in self._events_by_name:
            self.logger.warning(
                "BotApplication._ensure_event_name_available: duplicate event_name=%s",
                event_name,
            )
            raise ValueError(
                f"Event with name '{event_name}' is already registered."
            )
        if event_name in self._event_tasks:
            self.logger.warning(
                "BotApplication._ensure_event_name_available: shutting_down event_name=%s",
                event_name,
            )
            raise ValueError(
                f"Event with name '{event_name}' is still shutting down."
            )

    def _start_event_task(self, event: Event) -> None:
        """Create and track the task for a registered event.

        Args:
            event: Registered event whose task should be started.
        """
        task = asyncio.create_task(event.submit(self.stop_event))
        self._event_tasks[event.event_name] = task
        self._task_event_names[task] = event.event_name
        self._removed_event_names.discard(event.event_name)
        self.logger.debug(
            "BotApplication._start_event_task: started event_name=%s tracked_tasks=%d",
            event.event_name,
            len(self._event_tasks),
        )

    def _handle_event_task_completion(self, task: asyncio.Task[None]) -> None:
        """Process completion of an event task.

        Args:
            task: Completed task belonging to an event.

        Raises:
            RuntimeError: If an event task is cancelled unexpectedly.
            Exception: Re-raises unexpected event task failures.
        """
        event_name = self._task_event_names.pop(task, None)
        if event_name is None:
            self.logger.warning(
                "BotApplication._handle_event_task_completion: unknown_task",
            )
            return

        if self._event_tasks.get(event_name) is task:
            self._event_tasks.pop(event_name, None)

        was_removed = event_name in self._removed_event_names
        self.logger.debug(
            "BotApplication._handle_event_task_completion: completed event_name=%s cancelled=%s tracked_tasks=%d",
            event_name,
            task.cancelled(),
            len(self._event_tasks),
        )

        if task.cancelled():
            self._removed_event_names.discard(event_name)
            if was_removed or self.stop_event.is_set():
                self.logger.info(
                    "BotApplication._handle_event_task_completion: cancelled_expected "
                    "event_name=%s removed=%s stopping=%s",
                    event_name,
                    was_removed,
                    self.stop_event.is_set(),
                )
                return
            self.logger.critical(
                "BotApplication._handle_event_task_completion: cancelled_unexpected event_name=%s",
                event_name,
            )
            raise RuntimeError(
                f"Event '{event_name}' was cancelled unexpectedly."
            )

        exc = task.exception()
        if was_removed:
            self._removed_event_names.discard(event_name)
            if exc is None:
                self.logger.info(
                    "BotApplication._handle_event_task_completion: removed event_name=%s",
                    event_name,
                )
                return
            self.logger.error(
                "BotApplication._handle_event_task_completion: removed_task_failed event_name=%s error_type=%s",
                event_name,
                type(exc).__name__,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

        if exc is not None:
            self.logger.critical(
                "BotApplication._handle_event_task_completion: task_failed event_name=%s error_type=%s",
                event_name,
                type(exc).__name__,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise exc

    async def send_messages(
        self,
        messages: str | TelegramMessage | list[str | TelegramMessage],
    ) -> None:
        """Send one or more messages immediately.

        Args:
            messages: A single message (str or TelegramMessage) or a list of messages.
                      Strings are automatically wrapped in TelegramTextMessage.

        Example:
            await app.send_messages("Hello")  # Single text
            await app.send_messages(TelegramTextMessage("Hello"))  # Explicit
            await app.send_messages(["Hello", "World"])  # Multiple messages
            await app.send_messages([
                "Text message",
                TelegramImageMessage("path/to/image.png"),
            ])
        """
        # Normalize to list
        if not isinstance(messages, list):
            messages = [messages]

        self.logger.debug("BotApplication.send_messages: sending count=%d", len(messages))
        for message in messages:
            if isinstance(message, str):
                message = TelegramTextMessage(message)
            await message.send(bot=self.bot, chat_id=self.chat_id, logger=self.logger)
        self.logger.info("BotApplication.send_messages: sent count=%d", len(messages))
