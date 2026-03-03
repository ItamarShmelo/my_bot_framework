"""Bot testing dynamic mid-run event registration.

Tests:
- Registering new events while the bot is already running
- ActivateOnConditionEvent created and started mid-run
- Multiple dynamic events coexisting
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import List

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


def _make_add_heartbeat_handler(logger: logging.Logger):
    """Return an async handler that registers a new heartbeat event.

    Args:
        logger: Logger instance for the handler.

    Returns:
        An async function that returns an HTML string when invoked.
    """
    _event_index: List[int] = [0]

    async def _add_heartbeat() -> str:
        _event_index[0] += 1
        idx = _event_index[0]
        label = f"dynamic-{idx}"

        event = ActivateOnConditionEvent(
            event_name=f"dynamic_heartbeat_{idx}",
            condition=AlwaysTrueCondition(),
            message_builder=HeartbeatMessageBuilder(label),
            poll_seconds=HEARTBEAT_POLL_SECONDS,
        )
        get_app().register_event(event)
        logger.info(
            "_add_heartbeat: registered event_name=%s label=%s",
            event.event_name,
            label,
        )
        return (
            f"Registered new heartbeat event: <b>{label}</b> "
            f"(every {int(HEARTBEAT_POLL_SECONDS)} s)"
        )

    return _add_heartbeat


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

    app.register_command(SimpleCommand(
        command="/add_heartbeat",
        description="Register a new heartbeat event mid-run.",
        message_builder=_make_add_heartbeat_handler(logger),
    ))

    info_text = (
        "<b>Dynamic Event Bot</b>\n\n"
        "Tests dynamic mid-run event registration:\n"
        "• register_event() while the bot is already running\n"
        "• ActivateOnConditionEvent created at runtime\n"
        "• Multiple dynamic events coexisting"
    )
    app.register_command(SimpleCommand(
        command="/info",
        description="Show what this bot tests.",
        message_builder=lambda: info_text,
    ))

    async def send_startup_and_run() -> None:
        await app.send_messages(
            f"{info_text}\n\n"
            "Use /add_heartbeat to register a new periodic event at runtime."
        )
        logger.info("send_startup_and_run: starting")
        exit_code = await app.run()
        logger.info("send_startup_and_run: stopped exit_code=%d", exit_code)

    asyncio.run(send_startup_and_run())
    logger.info("main: stopped")


if __name__ == "__main__":
    main()
