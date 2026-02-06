"""Telegram update polling utilities.

This module provides:
- get_next_update_id(): Get the next update ID to poll from
- set_next_update_id(): Set the next update ID to poll from
- flush_pending_updates(): Clear pending updates on startup
- poll_updates(): Poll for Telegram updates
- get_chat_id_from_update(): Extract chat_id from an update
- UpdatePollerMixin: Mixin class for update polling with Template Method Pattern
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from telegram import Bot, Update

from .accessors import get_bot, get_chat_id, get_logger


# Module-level state for tracking Telegram update offset
_next_update_id: int = 0


def get_next_update_id() -> int:
    """Get the next update ID to poll from."""
    return _next_update_id


def set_next_update_id(value: int) -> None:
    """Set the next update ID to poll from."""
    global _next_update_id
    _next_update_id = value


async def flush_pending_updates(bot: Bot) -> None:
    """Flush all pending updates and set the next update ID.
    
    Call this when the bot starts to ignore old messages.
    
    Args:
        bot: The Telegram Bot instance.
    """
    logger = get_logger()
    logger.debug("flush_pending_updates: fetching pending updates")
    updates = await bot.get_updates(offset=-1, timeout=0)
    
    if updates:
        next_id = updates[-1].update_id + 1
        set_next_update_id(next_id)
        logger.info("flush_pending_updates: cleared=%d next_id=%d", len(updates), next_id)
    else:
        set_next_update_id(0)
        logger.info("flush_pending_updates: no_pending_updates")


async def poll_updates(bot: Bot, timeout: int = 5) -> List[Update]:
    """Poll for updates and update the global next_update_id."""
    updates_tuple = await bot.get_updates(
        offset=get_next_update_id(),
        timeout=timeout,
        allowed_updates=["message", "callback_query"],
    )
    updates = list(updates_tuple)
    if updates:
        set_next_update_id(max(updates, key=lambda u: u.update_id).update_id + 1)
        get_logger().debug("poll_updates: received count=%d", len(updates))
    return updates


def get_chat_id_from_update(update: Update) -> Optional[int]:
    """Extract chat_id from update."""
    if update.callback_query and update.callback_query.message:
        message = update.callback_query.message
        if message and hasattr(message, "chat_id"):
            return message.chat_id
    if update.message and hasattr(update.message, "chat_id"):
        return update.message.chat_id
    return None


class UpdatePollerMixin(ABC):
    """Mixin providing Telegram update polling with Template Method Pattern.
    
    Subclasses implement:
    - should_stop_polling(): when to exit the poll loop
    - handle_callback_update(update): process callback queries
    - handle_text_update(update): process text messages
    
    Uses singleton accessors (get_bot, get_chat_id, get_logger) for dependencies.
    """
    
    @abstractmethod
    def should_stop_polling(self) -> bool:
        """Return True when polling should stop."""
        ...
    
    @abstractmethod
    async def handle_callback_update(self, update: Update) -> None:
        """Handle a callback query update."""
        ...
    
    @abstractmethod
    async def handle_text_update(self, update: Update) -> None:
        """Handle a text message update."""
        ...
    
    async def poll(self) -> Any:
        """Template method: poll updates and route to handlers.
        
        Returns result (subclass-specific).
        """
        bot = get_bot()
        chat_id = get_chat_id()
        logger = get_logger()
        
        while not self.should_stop_polling():
            updates = await poll_updates(bot)
            
            for update in updates:
                update_chat_id = get_chat_id_from_update(update)
                if update_chat_id is None or str(update_chat_id) != chat_id:
                    logger.debug("UpdatePollerMixin.poll: filtered update wrong_chat=%s expected=%s", update_chat_id, chat_id)
                    continue
                
                if update.callback_query:
                    await self.handle_callback_update(update)
                elif update.message and update.message.text:
                    await self.handle_text_update(update)
        
        return self._get_poll_result()
    
    def _get_poll_result(self) -> Any:
        """Override to customize the result returned by poll()."""
        return None
