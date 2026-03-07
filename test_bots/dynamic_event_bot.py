"""Bot testing dynamic event registration and removal.

Tests:
- Startup heartbeat registration before runtime begins
- Pre-run removal before any event task exists
- Mid-run heartbeat registration with unique event names
- Targeted and bulk runtime removal of heartbeat events
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Callable, Coroutine, Dict, List

# Add grandparent directory to path for imports (to find my_bot_framework package)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from my_bot_framework import (
    ActivateOnConditionEvent,
    BotApplication,
    Condition,
    MessageBuilder,
    SimpleCommand,
    get_app,
)


_heartbeat_counter: int = 0
HEARTBEAT_POLL_SECONDS = 10.0
STARTUP_HEARTBEAT_EVENT_NAME = "startup_heartbeat_1"
REMOVED_BEFORE_RUN_EVENT_NAME = "startup_heartbeat_removed_before_run"


class AlwaysTrueCondition(Condition):
    """Condition that is always satisfied."""

    def __init__(self) -> None:
        """Initialize with no editable attributes."""
        self.editable_attributes = []

    def check(self) -> bool:
        """Always returns True."""
        return True


class HeartbeatMessageBuilder(MessageBuilder):
    """Build a numbered heartbeat message."""

    _label: str

    def __init__(self, label: str) -> None:
        """Initialize with a label for the heartbeat.

        Args:
            label: Display label included in each heartbeat message.
        """
        self.editable_attributes = []
        self._label = label

    def build(self) -> str:
        """Build a heartbeat message with a global counter."""
        global _heartbeat_counter  # noqa: PLW0603
        _heartbeat_counter += 1
        return f"[{self._label}] heartbeat #{_heartbeat_counter}"


def _register_heartbeat(
    app: BotApplication,
    logger: logging.Logger,
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
    event_name: str,
    label: str,
    origin: str,
) -> None:
    """Register a heartbeat event and track it for demo commands.

    Args:
        app: Application that owns the event.
        logger: Logger instance for the bot.
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.
        event_name: Unique event name to register.
        label: Human-readable heartbeat label.
        origin: Where the event was registered, such as startup or dynamic.
    """
    logger.debug(
        "_register_heartbeat: registering event_name=%s label=%s origin=%s active_before=%d",
        event_name,
        label,
        origin,
        len(heartbeat_names),
    )
    event = ActivateOnConditionEvent(
        event_name=event_name,
        condition=AlwaysTrueCondition(),
        message_builder=HeartbeatMessageBuilder(label),
        poll_seconds=HEARTBEAT_POLL_SECONDS,
    )
    app.register_event(event)
    heartbeat_names.append(event_name)
    heartbeat_labels[event_name] = label
    heartbeat_origins[event_name] = origin
    logger.info(
        "_register_heartbeat: registered event_name=%s label=%s origin=%s active_after=%d",
        event_name,
        label,
        origin,
        len(heartbeat_names),
    )


def _remove_heartbeat(
    app: BotApplication,
    logger: logging.Logger,
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
    event_name: str,
) -> str:
    """Remove a tracked heartbeat event and return a user-facing message.

    Args:
        app: Application that owns the event.
        logger: Logger instance for the bot.
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.
        event_name: Unique event name to remove.

    Returns:
        HTML message describing the removed event.
    """
    label = heartbeat_labels[event_name]
    origin = heartbeat_origins[event_name]
    logger.debug(
        "_remove_heartbeat: removing event_name=%s label=%s origin=%s active_before=%d",
        event_name,
        label,
        origin,
        len(heartbeat_names),
    )
    app.remove_event(event_name)
    heartbeat_names.remove(event_name)
    del heartbeat_labels[event_name]
    del heartbeat_origins[event_name]
    logger.info(
        "_remove_heartbeat: removed event_name=%s label=%s origin=%s active_after=%d",
        event_name,
        label,
        origin,
        len(heartbeat_names),
    )
    return (
        "Removed heartbeat event: "
        f"<b>{label}</b> (<code>{event_name}</code>, origin={origin})"
    )


def _make_add_heartbeat_handler(
    logger: logging.Logger,
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
) -> Callable[[], Coroutine[None, None, str]]:
    """Build a command handler that registers a new heartbeat event.

    Args:
        logger: Logger instance for the bot.
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.

    Returns:
        Async handler that registers a new heartbeat event and returns a
        user-facing confirmation message.
    """
    dynamic_event_index: List[int] = [0]

    async def _add_heartbeat() -> str:
        """Register the next dynamic heartbeat event."""
        dynamic_event_index[0] += 1
        heartbeat_index = dynamic_event_index[0]
        label = f"dynamic-{heartbeat_index}"
        event_name = f"dynamic_heartbeat_{heartbeat_index}"

        _register_heartbeat(
            app=get_app(),
            logger=logger,
            heartbeat_names=heartbeat_names,
            heartbeat_labels=heartbeat_labels,
            heartbeat_origins=heartbeat_origins,
            event_name=event_name,
            label=label,
            origin="dynamic",
        )
        return (
            "Registered new heartbeat event: "
            f"<b>{label}</b> (<code>{event_name}</code>, "
            f"every {int(HEARTBEAT_POLL_SECONDS)} s)"
        )

    return _add_heartbeat


def _make_remove_last_heartbeat_handler(
    logger: logging.Logger,
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
) -> Callable[[], Coroutine[None, None, str]]:
    """Build a command handler that removes the most recent heartbeat.

    Args:
        logger: Logger instance for the bot.
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.

    Returns:
        Async handler that removes the most recently registered heartbeat and
        returns a user-facing confirmation message.
    """

    async def _remove_last_heartbeat() -> str:
        """Remove the most recently registered heartbeat event."""
        if not heartbeat_names:
            logger.info("_remove_last_heartbeat: no_events")
            return "No heartbeat events are currently registered."

        event_name = heartbeat_names[-1]
        logger.debug("_remove_last_heartbeat: selected event_name=%s", event_name)
        return _remove_heartbeat(
            app=get_app(),
            logger=logger,
            heartbeat_names=heartbeat_names,
            heartbeat_labels=heartbeat_labels,
            heartbeat_origins=heartbeat_origins,
            event_name=event_name,
        )

    return _remove_last_heartbeat


def _make_remove_named_heartbeat_handler(
    logger: logging.Logger,
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
    event_name: str,
) -> Callable[[], Coroutine[None, None, str]]:
    """Build a command handler that removes a specific heartbeat by name.

    Args:
        logger: Logger instance for the bot.
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.
        event_name: Unique heartbeat event name to remove when invoked.

    Returns:
        Async handler that removes the requested heartbeat if it is active.
    """

    async def _remove_named_heartbeat() -> str:
        """Remove a specific tracked heartbeat event by exact name."""
        if event_name not in heartbeat_names:
            logger.info(
                "_remove_named_heartbeat: event_not_active event_name=%s",
                event_name,
            )
            return (
                "Heartbeat event is not currently registered: "
                f"<code>{event_name}</code>"
            )

        logger.debug("_remove_named_heartbeat: selected event_name=%s", event_name)
        return _remove_heartbeat(
            app=get_app(),
            logger=logger,
            heartbeat_names=heartbeat_names,
            heartbeat_labels=heartbeat_labels,
            heartbeat_origins=heartbeat_origins,
            event_name=event_name,
        )

    return _remove_named_heartbeat


def _make_remove_all_heartbeats_handler(
    logger: logging.Logger,
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
) -> Callable[[], Coroutine[None, None, str]]:
    """Build a command handler that removes all tracked heartbeats.

    Args:
        logger: Logger instance for the bot.
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.

    Returns:
        Async handler that removes every tracked heartbeat and returns a
        user-facing summary message.
    """

    async def _remove_all_heartbeats() -> str:
        """Remove every currently tracked heartbeat event."""
        if not heartbeat_names:
            logger.info("_remove_all_heartbeats: no_events")
            return "No heartbeat events are currently registered."

        removed_names = list(reversed(heartbeat_names))
        logger.info(
            "_remove_all_heartbeats: removing count=%d",
            len(removed_names),
        )
        removed_messages = [
            _remove_heartbeat(
                app=get_app(),
                logger=logger,
                heartbeat_names=heartbeat_names,
                heartbeat_labels=heartbeat_labels,
                heartbeat_origins=heartbeat_origins,
                event_name=event_name,
            )
            for event_name in removed_names
        ]
        return "<b>Removed all heartbeat events</b>\n" + "\n".join(removed_messages)

    return _remove_all_heartbeats


def _make_list_heartbeats_handler(
    heartbeat_names: List[str],
    heartbeat_labels: Dict[str, str],
    heartbeat_origins: Dict[str, str],
) -> Callable[[], str]:
    """Build a command handler that lists the tracked heartbeat events.

    Args:
        heartbeat_names: Ordered list of active heartbeat event names.
        heartbeat_labels: Mapping of event name to display label.
        heartbeat_origins: Mapping of event name to registration origin.

    Returns:
        Handler that renders the current heartbeat registry for the user.
    """

    def _list_heartbeats() -> str:
        """Render the list of currently registered heartbeat events."""
        if not heartbeat_names:
            return "No heartbeat events are currently registered."

        lines = ["<b>Registered heartbeat events</b>"]
        for index, event_name in enumerate(heartbeat_names, start=1):
            label = heartbeat_labels[event_name]
            origin = heartbeat_origins[event_name]
            lines.append(
                f"{index}. <code>{event_name}</code> - <b>{label}</b> ({origin})"
            )
        return "\n".join(lines)

    return _list_heartbeats


def get_credentials() -> tuple[str, str]:
    """Get bot credentials from .token and .chat_id files in test_bots directory.

    Returns:
        Tuple of (token, chat_id) from credential files.

    Raises:
        RuntimeError: If .token or .chat_id files are missing or empty.
    """
    logger = logging.getLogger("dynamic_event_bot")
    logger.debug("get_credentials: loading credentials")
    test_bots_dir = Path(__file__).resolve().parent
    token_file = test_bots_dir / ".token"
    chat_id_file = test_bots_dir / ".chat_id"

    if not token_file.exists() or not chat_id_file.exists():
        logger.error("get_credentials: missing_credential_files")
        raise RuntimeError(
            "Missing credential files. Create .token and .chat_id files in test_bots directory."
        )

    token = token_file.read_text().strip()
    chat_id = chat_id_file.read_text().strip()

    if not token or not chat_id:
        logger.error("get_credentials: empty_credential_files")
        raise RuntimeError(
            "Empty credential files. Ensure .token and .chat_id contain valid values."
        )
    logger.debug("get_credentials: loaded successfully")
    return token, chat_id


def main() -> None:
    """Run the dynamic event test bot."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("dynamic_event_bot")
    logger.info("main: starting")

    token, chat_id = get_credentials()

    app = BotApplication.initialize(
        token=token,
        chat_id=chat_id,
        logger=logger,
    )

    heartbeat_names: List[str] = []
    heartbeat_labels: Dict[str, str] = {}
    heartbeat_origins: Dict[str, str] = {}

    _register_heartbeat(
        app=app,
        logger=logger,
        heartbeat_names=heartbeat_names,
        heartbeat_labels=heartbeat_labels,
        heartbeat_origins=heartbeat_origins,
        event_name=STARTUP_HEARTBEAT_EVENT_NAME,
        label="startup-1",
        origin="startup",
    )
    _register_heartbeat(
        app=app,
        logger=logger,
        heartbeat_names=heartbeat_names,
        heartbeat_labels=heartbeat_labels,
        heartbeat_origins=heartbeat_origins,
        event_name=REMOVED_BEFORE_RUN_EVENT_NAME,
        label="startup-removed-before-run",
        origin="startup",
    )
    _remove_heartbeat(
        app=app,
        logger=logger,
        heartbeat_names=heartbeat_names,
        heartbeat_labels=heartbeat_labels,
        heartbeat_origins=heartbeat_origins,
        event_name=REMOVED_BEFORE_RUN_EVENT_NAME,
    )
    logger.info(
        "main: configured_heartbeats active=%d",
        len(heartbeat_names),
    )

    app.register_command(SimpleCommand(
        command="/add_heartbeat",
        description="Register a new heartbeat event while the bot is running.",
        message_builder=_make_add_heartbeat_handler(
            logger,
            heartbeat_names,
            heartbeat_labels,
            heartbeat_origins,
        ),
    ))
    app.register_command(SimpleCommand(
        command="/remove_last_heartbeat",
        description="Remove the most recently registered heartbeat event.",
        message_builder=_make_remove_last_heartbeat_handler(
            logger,
            heartbeat_names,
            heartbeat_labels,
            heartbeat_origins,
        ),
    ))
    app.register_command(SimpleCommand(
        command="/remove_startup_heartbeat",
        description="Remove the startup heartbeat by its exact event name.",
        message_builder=_make_remove_named_heartbeat_handler(
            logger=logger,
            heartbeat_names=heartbeat_names,
            heartbeat_labels=heartbeat_labels,
            heartbeat_origins=heartbeat_origins,
            event_name=STARTUP_HEARTBEAT_EVENT_NAME,
        ),
    ))
    app.register_command(SimpleCommand(
        command="/remove_all_heartbeats",
        description="Remove every currently registered heartbeat event.",
        message_builder=_make_remove_all_heartbeats_handler(
            logger,
            heartbeat_names,
            heartbeat_labels,
            heartbeat_origins,
        ),
    ))
    app.register_command(SimpleCommand(
        command="/list_heartbeats",
        description="List all currently registered heartbeat events.",
        message_builder=_make_list_heartbeats_handler(
            heartbeat_names,
            heartbeat_labels,
            heartbeat_origins,
        ),
    ))

    info_text = (
        "<b>Dynamic Event Bot</b>\n\n"
        "Tests dynamic event lifecycle management for heartbeat events:\n"
        "• startup registration before calling run()\n"
        "• pre-run removal before any event task exists\n"
        "• mid-run registration with unique event names\n"
        "• targeted runtime removal by exact event name\n"
        "• bulk runtime removal without stopping the bot\n\n"
        f"Active startup heartbeat: <code>{STARTUP_HEARTBEAT_EVENT_NAME}</code>\n"
        "Pre-run removal demo: "
        f"<code>{REMOVED_BEFORE_RUN_EVENT_NAME}</code> was registered and removed "
        "before calling run()\n"
        "Intentional runtime removals should only cancel the selected heartbeat task."
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests.",
        message_builder=lambda: info_text,
    ))

    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"{info_text}\n\n"
            "Use /add_heartbeat to register a new periodic event, "
            "/remove_startup_heartbeat to remove the startup heartbeat by name, "
            "/remove_last_heartbeat to remove the newest dynamic heartbeat, "
            "/remove_all_heartbeats to clear them all, and /list_heartbeats "
            "to inspect the active set."
        )
        logger.info("send_startup_and_run: starting")
        exit_code = await app.run()
        logger.info("send_startup_and_run: stopped exit_code=%d", exit_code)

    asyncio.run(send_startup_and_run())
    logger.info("main: stopped")


if __name__ == "__main__":
    main()
