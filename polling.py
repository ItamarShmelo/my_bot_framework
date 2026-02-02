"""Telegram update polling utilities.

This module provides:
- poll_updates(): Poll for Telegram updates
- get_chat_id_from_update(): Extract chat_id from an update
- flush_pending_updates(): Clear pending updates on startup
- UpdatePollerMixin: Mixin class for update polling with Template Method Pattern
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple

from telegram import Bot, Update

from .accessors import get_bot, get_chat_id, get_logger


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
    
    async def poll(self, update_offset: int = 0) -> Tuple[Any, int]:
        """Template method: poll updates and route to handlers.
        
        Returns (result, final_offset). Result meaning is subclass-specific.
        """
        bot = get_bot()
        chat_id = get_chat_id()
        
        current_offset = update_offset
        while not self.should_stop_polling():
            updates, current_offset = await poll_updates(bot, chat_id, current_offset)
            
            for update in updates:
                update_chat_id = get_chat_id_from_update(update)
                if update_chat_id is None or str(update_chat_id) != chat_id:
                    continue
                
                if update.callback_query:
                    await self.handle_callback_update(update)
                elif update.message and update.message.text:
                    await self.handle_text_update(update)
        
        return self._get_poll_result(), current_offset
    
    def _get_poll_result(self) -> Any:
        """Override to customize the result returned by poll()."""
        return None
