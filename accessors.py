"""Singleton accessor functions for the BotApplication.

This module provides accessor functions that retrieve components from the
BotApplication singleton. It exists as a separate module to break circular
import dependencies - other modules can import these accessors without
importing bot_application.py directly.

The singleton instance is set by BotApplication.initialize().
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Bot
    from .bot_application import BotApplication


# The singleton instance, set by BotApplication
_instance: "BotApplication | None" = None


def _set_instance(app: "BotApplication") -> None:
    """Set the singleton instance. Called by BotApplication.initialize()."""
    global _instance
    _instance = app


def _get_instance() -> "BotApplication":
    """Get the singleton instance, raising if not initialized."""
    if _instance is None:
        raise RuntimeError(
            "BotApplication not initialized. Call BotApplication.initialize() first."
        )
    return _instance


def get_app() -> "BotApplication":
    """Get the BotApplication singleton instance."""
    return _get_instance()


def get_bot() -> "Bot":
    """Get the Bot instance from the singleton."""
    return _get_instance().bot


def get_chat_id() -> str:
    """Get the chat_id from the singleton."""
    return _get_instance().chat_id


def get_queue() -> asyncio.Queue:
    """Get the message queue from the singleton."""
    return _get_instance().queue


def get_stop_event() -> asyncio.Event:
    """Get the stop event from the singleton."""
    return _get_instance().stop_event


def get_logger() -> logging.Logger:
    """Get the logger from the singleton."""
    return _get_instance().logger
