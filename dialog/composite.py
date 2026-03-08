"""Composite dialogs: Sequence, Branch, Loop, and DialogHandler."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..accessors import get_logger
from .base import Dialog, DialogResult, DialogState


class SequenceDialog(Dialog[dict[str, Any]]):
    """Composite dialog: Run child dialogs in sequence.

    Supports named dialogs for easy value access:
    - SequenceDialog([dialog1, dialog2])  # Anonymous, indexed access
    - SequenceDialog([("name", dialog), ("age", dialog)])  # Named access

    Updates shared context as each dialog completes.
    Does NOT poll — delegates to children.
    """

    def __init__(
        self,
        dialogs: list[Dialog[Any] | tuple[str, Dialog[Any]]],
    ) -> None:
        """Create a sequence dialog.

        Args:
            dialogs: List of dialogs or (name, dialog) tuples.
        """
        super().__init__()
        self._dialogs: list[tuple[str, Dialog[Any]]] = []
        for i, item in enumerate(dialogs):
            if isinstance(item, tuple):
                name, dialog = item
                self._dialogs.append((name, dialog))
            else:
                self._dialogs.append((f"step_{i}", item))
        self._current_index: int = 0

    async def _run_dialog(self) -> dict[str, Any] | DialogResult:
        """Run each child's start() in sequence."""
        self.state = DialogState.ACTIVE
        self._current_index = 0

        get_logger().debug(
            "SequenceDialog._run_dialog: started steps=%d",
            len(self._dialogs),
        )

        if not self._dialogs:
            self.state = DialogState.COMPLETE
            get_logger().info("SequenceDialog._run_dialog: completed empty_sequence")
            return {}

        for name, dialog in self._dialogs:
            result = await dialog.start(self.context)
            self.context[name] = result
            self._current_index += 1

            if isinstance(result, DialogResult):
                self._dialog_result = DialogResult.CANCELLED
                self.state = DialogState.COMPLETE
                get_logger().info(
                    "SequenceDialog._run_dialog: cancelled step=%s",
                    name,
                )
                return DialogResult.CANCELLED

        self._dialog_result = {name: d.dialog_result for name, d in self._dialogs}
        self.state = DialogState.COMPLETE
        get_logger().info(
            "SequenceDialog._run_dialog: completed steps=%d values=%s",
            len(self._dialogs),
            list(self._dialog_result.keys()) if isinstance(self._dialog_result, dict) else self._dialog_result,
        )
        return self.dialog_result

    @property
    def current_dialog(self) -> Dialog[Any] | None:
        """Get the currently active child dialog."""
        if self._current_index < len(self._dialogs):
            return self._dialogs[self._current_index][1]
        return None

    @property
    def values(self) -> dict[str, Any]:
        """Named values dict: {name: dialog.dialog_result}"""
        return {name: d.dialog_result for name, d in self._dialogs}

    def reset(self) -> None:
        """Reset sequence and all child dialogs."""
        super().reset()
        self._current_index = 0
        for _, dialog in self._dialogs:
            dialog.reset()


class BranchDialog(Dialog[dict[str, Any] | None]):
    """Composite dialog: Condition-based branching.

    Evaluates a condition function on start to select which branch to run.
    Does NOT poll — delegates to selected branch.
    """

    def __init__(
        self,
        condition: Callable[[dict[str, Any]], str],
        branches: dict[str, Dialog[Any]],
    ) -> None:
        """Create a branch dialog.

        Args:
            condition: Callable(context) -> branch_key
            branches: Dict mapping branch keys to dialogs
        """
        super().__init__()
        self.condition = condition
        self.branches = branches
        self._active_branch: Dialog[Any] | None = None
        self._active_key: str | None = None

    async def _run_dialog(self) -> dict[str, Any] | None | DialogResult:
        """Evaluate condition and run selected branch."""
        self.state = DialogState.ACTIVE

        branch_key = self.condition(self.context)
        get_logger().debug(
            "BranchDialog._run_dialog: condition_evaluated branch_key=%s",
            branch_key,
        )

        if branch_key not in self.branches:
            get_logger().error(
                "BranchDialog._run_dialog: key_not_found key=%s branches=%s",
                branch_key,
                list(self.branches.keys()),
            )
            self._dialog_result = DialogResult.CANCELLED
            self.state = DialogState.COMPLETE
            return DialogResult.CANCELLED

        self._active_key = branch_key
        self._active_branch = self.branches[branch_key]

        get_logger().info(
            "BranchDialog._run_dialog: running_branch key=%s",
            self._active_key,
        )
        result = await self._active_branch.start(self.context)
        self._dialog_result = {self._active_key: result}
        self.state = DialogState.COMPLETE
        get_logger().info(
            "BranchDialog._run_dialog: completed key=%s",
            self._active_key,
        )
        return self.dialog_result

    def reset(self) -> None:
        """Reset branch dialog."""
        super().reset()
        self._active_branch = None
        self._active_key = None
        for dialog in self.branches.values():
            dialog.reset()


class LoopDialog(Dialog[Any]):
    """Composite dialog: Repeat a dialog until exit condition.

    Runs the inner dialog repeatedly until:
    - dialog_result is CANCELLED, OR
    - dialog_result == exit_value, OR
    - exit_condition(dialog_result) returns True, OR
    - max_iterations reached

    Does NOT poll — delegates to inner dialog.
    """

    def __init__(
        self,
        dialog: Dialog[Any],
        exit_value: Any = None,
        exit_condition: Callable[[Any], bool] | None = None,
        max_iterations: int | None = None,
    ) -> None:
        """Create a loop dialog.

        Args:
            dialog: The dialog to repeat.
            exit_value: Exit when dialog.dialog_result == this value.
            exit_condition: Exit when this callable returns True.
            max_iterations: Maximum number of iterations (safety limit).
        """
        super().__init__()
        self.dialog = dialog
        self.exit_value = exit_value
        self.exit_condition = exit_condition
        self.max_iterations = max_iterations
        self._iterations = 0
        self._all_values: list[Any] = []

    async def _run_dialog(self) -> Any:
        """Run inner dialog repeatedly until exit condition."""
        self.state = DialogState.ACTIVE
        self._iterations = 0
        self._all_values = []

        get_logger().debug(
            "LoopDialog._run_dialog: started max_iterations=%s",
            self.max_iterations,
        )

        while True:
            result = await self.dialog.start(self.context)

            if isinstance(result, DialogResult):
                self._dialog_result = DialogResult.CANCELLED
                self.state = DialogState.COMPLETE
                get_logger().info(
                    "LoopDialog._run_dialog: cancelled iteration=%d",
                    self._iterations,
                )
                return DialogResult.CANCELLED

            self._all_values.append(result)
            self._iterations += 1

            get_logger().debug(
                "LoopDialog._run_dialog: iteration=%d result=%s",
                self._iterations,
                result,
            )

            if self._should_exit(result):
                self._dialog_result = result
                self.state = DialogState.COMPLETE
                get_logger().info(
                    "LoopDialog._run_dialog: completed iterations=%d",
                    self._iterations,
                )
                return self.dialog_result

    def _should_exit(self, result: Any) -> bool:
        """Check if the loop should exit based on result."""
        if isinstance(result, DialogResult):
            return True
        if self.exit_value is not None and result == self.exit_value:
            return True
        if self.exit_condition is not None and self.exit_condition(result):
            return True
        if self.max_iterations is not None and self._iterations >= self.max_iterations:
            return True
        return False

    def reset(self) -> None:
        """Reset loop dialog."""
        super().reset()
        self._iterations = 0
        self._all_values = []
        self.dialog.reset()


class DialogHandler(Dialog[Any]):
    """Composite dialog: Wraps a dialog, runs it, calls on_complete.

    Does NOT poll — delegates to inner dialog.
    Provides a hook to process results after dialog completion.
    """

    def __init__(
        self,
        dialog: Dialog[Any],
        on_complete: Callable[[Any], Any] | None = None,
    ) -> None:
        """Create a dialog handler.

        Args:
            dialog: The dialog to wrap.
            on_complete: Optional callback to call with the result.
                         Can be sync or async.
        """
        super().__init__()
        self.dialog = dialog
        self.on_complete = on_complete

    async def _run_dialog(self) -> Any:
        """Run inner dialog and call on_complete handler."""
        get_logger().debug("DialogHandler._run_dialog: started")
        result = await self.dialog.start(self.context)

        if self.on_complete:
            maybe_awaitable = self.on_complete(result)
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

        self._dialog_result = result
        self.state = DialogState.COMPLETE
        get_logger().info("DialogHandler._run_dialog: completed")
        return self.dialog_result

    def reset(self) -> None:
        """Reset handler and inner dialog."""
        super().reset()
        self.dialog.reset()
