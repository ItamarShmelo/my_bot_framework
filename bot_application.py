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
        self.events: List["Event"] = []
        self.commands: List["Command"] = []
    
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
            logger.warning("BotApplication already initialized, returning existing instance")
            return cls._instance
        
        bot = Bot(token=token)
        cls._instance = cls(bot, chat_id, logger)
        _set_instance(cls._instance)  # Set the accessor singleton
        logger.info("bot_application_initialized chat_id=%s", chat_id)
        return cls._instance
    
    def register_event(self, event: "Event") -> None:
        """Register an event to be run when the bot starts."""
        self.events.append(event)
        self.logger.debug("event_registered event_name=%s", event.event_name)
    
    def register_command(self, command: "Command") -> None:
        """Register a command to be available to users."""
        self.commands.append(command)
        self.logger.debug("command_registered command=%s", command.command)
    
    async def terminate(self) -> None:
        """Built-in terminate handler - sends goodbye and sets stop_event."""
        self.logger.info("bot_terminate_requested")
        await self.send_messages("Bot terminating. Goodbye!")
        self.stop_event.set()
    
    def list_commands(self) -> str:
        """Built-in commands list handler - returns formatted list of all commands."""
        lines = [f"{cmd.command}: {cmd.description}" for cmd in self.commands]
        return "\n".join(lines)
    
    async def run(self) -> int:
        """Run the bot application.
        
        Starts all registered events and the commands handler.
        Automatically registers built-in commands (/terminate, /commands).
        Blocks until stop_event is set.
        
        Returns:
            Exit code (0 for success).
        """
        # Register built-in commands
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
        
        # Flush pending updates to only process new messages
        initial_offset = await flush_pending_updates(self.bot)
        
        # Create the commands event
        commands_event = CommandsEvent(
            event_name="commands",
            commands=self.commands,
            initial_offset=initial_offset,
        )
        self.events.append(commands_event)
        
        # Start all event tasks
        event_tasks = [
            asyncio.create_task(event.submit(self.stop_event))
            for event in self.events
        ]
        
        self.logger.info("bot_application_started events=%d commands=%d",
                         len(self.events), len(self.commands))
        
        # Wait for stop signal
        await self.stop_event.wait()
        
        self.logger.info("bot_application_stopping")
        
        # Cancel all tasks
        for task in event_tasks:
            task.cancel()
        
        # Wait for cancellation
        await asyncio.gather(*event_tasks, return_exceptions=True)
        
        self.logger.info("bot_application_stopped")
        return 0
    
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
        
        for message in messages:
            if isinstance(message, str):
                message = TelegramTextMessage(message)
            await message.send(bot=self.bot, chat_id=self.chat_id, logger=self.logger)


# Re-export accessor functions from accessors module for backward compatibility
from .accessors import (
    get_app,
    get_bot,
    get_chat_id,
    get_stop_event,
    get_logger,
)
