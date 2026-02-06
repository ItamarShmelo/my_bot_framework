"""BotApplication singleton for managing Telegram bot lifecycle."""

import asyncio
import logging
from typing import List, Optional, Union

from telegram import Bot

from .telegram_utilities import TelegramMessage, TelegramTextMessage
from .accessors import _set_instance
from .event import Command, Event, SimpleCommand, CommandsEvent
from .polling import flush_pending_updates


class BotApplication:
    """Singleton class managing the Telegram bot application.

    Encapsulates the bot instance, events, and commands.
    Provides built-in /terminate and /commands functionality.

    Usage:
        app = BotApplication.initialize(
            token="YOUR_BOT_TOKEN",
            chat_id="YOUR_CHAT_ID",
            logger=your_logger,
        )
        app.register_event(my_event)
        app.register_command(my_command)
        await app.run()
    """

    _instance: Optional["BotApplication"] = None

    bot: Bot
    chat_id: str
    logger: logging.Logger
    stop_event: asyncio.Event
    events: List["Event"]
    commands: List["Command"]

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
        self.commands = []

    @classmethod
    def get_instance(cls) -> "BotApplication":
        """Get the singleton instance.

        Raises:
            RuntimeError: If initialize() hasn't been called.
        """
        if cls._instance is None:
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
    ) -> "BotApplication":
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

    def register_event(self, event: "Event") -> None:
        """Register an event to be run when the bot starts."""
        self.events.append(event)
        self.logger.debug("BotApplication.register_event: registered event_name=%s", event.event_name)

    def register_command(self, command: "Command") -> None:
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
        return "\n".join(lines)

    async def run(self) -> int:
        """Run the bot application.

        Registers built-in commands, initializes the HTTP session, then
        enters the event loop. Blocks until stop_event is set or a fatal
        error terminates the bot.

        Returns:
            Exit code (0 for success).
        """
        self._register_builtin_commands()
        self.logger.info(
            "BotApplication.run: starting events=%d commands=%d",
            len(self.events),
            len(self.commands),
        )
        await self._initialize_http_session()
        return await self._run_event_loop()

    def _register_builtin_commands(self) -> None:
        """Register /terminate, /commands, and the CommandsEvent."""
        self.commands.insert(0, SimpleCommand(
            command="/terminate",
            description="Terminate the bot and shut down.",
            message_builder=self.terminate,
        ))
        self.commands.append(SimpleCommand(
            command="/commands",
            description="List all available commands.",
            message_builder=self.list_commands,
        ))
        commands_event = CommandsEvent(
            event_name="commands",
            commands=self.commands,
        )
        self.events.append(commands_event)

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
        """Flush updates, start event tasks, and wait for stop or fatal error.

        Detects task failures so that fatal exceptions (e.g. InvalidHtmlError,
        unexpected condition/builder crashes) propagate and terminate the bot
        instead of being silently swallowed.

        Returns:
            Exit code (0 for success).
        """
        try:
            await flush_pending_updates(self.bot)

            event_tasks = [
                asyncio.create_task(event.submit(self.stop_event))
                for event in self.events
            ]

            self.logger.info(
                "BotApplication._run_event_loop: started events=%d commands=%d",
                len(self.events),
                len(self.commands),
            )

            # Wait for either stop_event or a task failure (fatal error)
            stop_task = asyncio.create_task(self.stop_event.wait())
            done, pending = await asyncio.wait(
                event_tasks + [stop_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # If an event task failed, re-raise its exception (fatal)
            for task in done:
                if task is not stop_task:
                    exc = task.exception()
                    if exc is not None:
                        raise exc

            # Normal shutdown -- cancel remaining tasks
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            self.logger.info("BotApplication._run_event_loop: stopped")
            return 0
        except Exception:
            self.logger.critical(
                "BotApplication._run_event_loop: fatal",
                exc_info=True,
            )
            raise
        finally:
            try:
                self.logger.debug("BotApplication._run_event_loop: shutting down HTTP session")
                await self.bot.shutdown()
                self.logger.debug("BotApplication._run_event_loop: HTTP session shut down")
            except Exception:
                self.logger.critical(
                    "BotApplication._run_event_loop: http_session_shutdown_failed",
                    exc_info=True,
                )

    async def send_messages(
        self,
        messages: Union[str, TelegramMessage, List[Union[str, TelegramMessage]]],
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
        self.logger.debug("BotApplication.send_messages: sent count=%d", len(messages))
