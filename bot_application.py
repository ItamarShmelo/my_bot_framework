"""BotApplication singleton for managing Telegram bot lifecycle."""

import asyncio
import logging
from typing import TYPE_CHECKING, List, Optional

from telegram import Bot

if TYPE_CHECKING:
    from .event import Command, Event, EventMessage


class BotApplication:
    """Singleton class managing the Telegram bot application.
    
    Encapsulates the bot instance, message queue, events, and commands.
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
        self.queue: asyncio.Queue["EventMessage"] = asyncio.Queue()
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
        logger.info("bot_application_initialized chat_id=%s", chat_id)
        return cls._instance
    
    def register_event(self, event: "Event") -> None:
        """Register an event to be run when the bot starts."""
        self.events.append(event)
        self.logger.debug("event_registered title=%s", event.title)
    
    def register_command(self, command: "Command") -> None:
        """Register a command to be available to users."""
        self.commands.append(command)
        self.logger.debug("command_registered command=%s", command.command)
    
    def terminate(self) -> str:
        """Built-in terminate handler - sets stop_event to shut down the bot."""
        self.logger.info("bot_terminate_requested")
        self.stop_event.set()
        return "Bot terminating. Goodbye!"
    
    def list_commands(self) -> str:
        """Built-in commands list handler - returns formatted list of all commands."""
        lines = [f"{cmd.command}: {cmd.description}" for cmd in self.commands]
        return "\n".join(lines)
    
    async def run(self) -> int:
        """Run the bot application.
        
        Starts the message sender worker and all registered events.
        Automatically registers built-in commands (/terminate, /commands).
        Blocks until stop_event is set.
        
        Returns:
            Exit code (0 for success).
        """
        from .event import SimpleCommand, TelegramCommandsEvent, flush_pending_updates
        
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
        commands_event = TelegramCommandsEvent(
            title="commands",
            bot=self.bot,
            allowed_chat_id=self.chat_id,
            commands=self.commands,
            initial_offset=initial_offset,
        )
        self.events.append(commands_event)
        
        # Start message sender worker
        sender_task = asyncio.create_task(self._message_sender())
        
        # Start all event tasks
        event_tasks = [
            asyncio.create_task(event.submit(self.queue, self.stop_event))
            for event in self.events
        ]
        
        self.logger.info("bot_application_started events=%d commands=%d",
                         len(self.events), len(self.commands))
        
        # Wait for stop signal
        await self.stop_event.wait()
        
        # Drain the queue
        self.logger.info("bot_application_stopping")
        await self.queue.join()
        
        # Cancel all tasks
        for task in event_tasks:
            task.cancel()
        sender_task.cancel()
        
        # Wait for cancellation
        await asyncio.gather(*event_tasks, sender_task, return_exceptions=True)
        
        self.logger.info("bot_application_stopped")
        return 0
    
    async def _message_sender(self) -> None:
        """Continuously drain the queue and send messages via the bot."""
        while True:
            if self.stop_event.is_set() and self.queue.empty():
                return
            try:
                message = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await message.message_body.send(
                    bot=self.bot,
                    chat_id=self.chat_id,
                    title=message.message_title,
                    logger=self.logger,
                )
            finally:
                self.queue.task_done()
            await asyncio.sleep(0.05)
    
    async def send_message(self, message: "EventMessage") -> None:
        """Enqueue a message for sending."""
        await self.queue.put(message)


# Module-level accessor functions
def get_app() -> BotApplication:
    """Get the BotApplication singleton instance."""
    return BotApplication.get_instance()


def get_bot() -> Bot:
    """Get the Bot instance from the singleton."""
    return BotApplication.get_instance().bot


def get_chat_id() -> str:
    """Get the chat_id from the singleton."""
    return BotApplication.get_instance().chat_id


def get_queue() -> asyncio.Queue:
    """Get the message queue from the singleton."""
    return BotApplication.get_instance().queue


def get_stop_event() -> asyncio.Event:
    """Get the stop event from the singleton."""
    return BotApplication.get_instance().stop_event


def get_logger() -> logging.Logger:
    """Get the logger from the singleton."""
    return BotApplication.get_instance().logger
