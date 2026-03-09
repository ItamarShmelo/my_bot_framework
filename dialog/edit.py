"""EditEventDialog — dialog for editing an event's editable attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..accessors import get_app, get_logger
from .base import (
    DONE_CALLBACK,
    Dialog,
    DialogResult,
    DialogState,
    KeyboardType,
    is_cancelled,
)
from .factories import create_choice_dialog, create_confirm_dialog
from .input import UserInputDialog

if TYPE_CHECKING:
    from ..editable import EditableAttribute
    from ..event import ActivateOnConditionEvent


class EditEventDialog(Dialog[dict[str, Any]]):
    """Dialog for editing an event's editable attributes.

    Supports both inline and reply keyboard modes via the keyboard_type
    parameter. Delegates to ChoiceDialog for field selection and boolean
    fields, and UserInputDialog for text fields. Does not poll directly.

    Shows a list of editable fields as buttons. Supports:
    - Boolean fields: Toggle buttons [True] [False] via ConfirmDialog
    - Other fields: Text input via UserInputDialog

    Edits are staged in ``_staged_edits`` and only applied when clicking Done.
    Supports optional cross-field validation after each field edit.

    Example:
        def validate_range(staged_edits):
            min_val = staged_edits.get("condition.limit_min", event.get("condition.limit_min"))
            max_val = staged_edits.get("condition.limit_max", event.get("condition.limit_max"))
            if min_val is not None and max_val is not None and min_val >= max_val:
                return False, "limit_min must be < limit_max"
            return True, ""

        dialog = EditEventDialog(my_event, validator=validate_range)
        dialog_reply = EditEventDialog(my_event, keyboard_type=KeyboardType.REPLY)
    """

    def __init__(
        self,
        event: ActivateOnConditionEvent,
        validator: Callable[[dict[str, Any]], tuple[bool, str]] | None = None,
        keyboard_type: KeyboardType = KeyboardType.INLINE,
    ) -> None:
        """Create an edit event dialog.

        Args:
            event: The event with editable_attributes to edit.
            validator: Optional cross-field validation function.
                Receives dict of staged edits, returns (is_valid, error_msg).
                Called after each successful field edit.
            keyboard_type: Type of keyboard to use for field selection and
                boolean editing (INLINE or REPLY). Defaults to INLINE.
        """
        super().__init__()
        self.event = event
        self.validator = validator
        self.keyboard_type = keyboard_type
        self._staged_edits: dict[str, Any] = {}
        get_logger().info(
            "EditEventDialog.__init__: initialized event=%s keyboard_type=%s",
            event.event_name,
            keyboard_type.value,
        )

    async def _run_dialog(self) -> dict[str, Any] | DialogResult:
        """Run the edit dialog loop until Done or Cancel."""
        self.state = DialogState.ACTIVE
        self._staged_edits = {}
        logger = get_logger()
        logger.info("EditEventDialog._run_dialog: started")

        while True:
            field_dialog = create_choice_dialog(
                prompt=self._get_field_list_prompt(),
                choices=self._build_field_choices,
                keyboard_type=self.keyboard_type,
                include_cancel=True,
            )
            result = await field_dialog.start(self.context)

            if is_cancelled(result):
                self._dialog_result = DialogResult.CANCELLED
                self.state = DialogState.COMPLETE
                logger.info("EditEventDialog._run_dialog: cancelled")
                return DialogResult.CANCELLED

            if result == DONE_CALLBACK:
                self._apply_all_edits()
                self._dialog_result = dict(self._staged_edits)
                self.state = DialogState.COMPLETE
                logger.info("EditEventDialog._run_dialog: done edits=%s", self._staged_edits)
                return self.dialog_result

            if not isinstance(result, str):
                logger.debug(
                    "EditEventDialog._run_dialog: skip_invalid_result result_type=%s",
                    type(result).__name__,
                )
                continue
            field_name = result
            if field_name not in self.event.editable_attributes:
                logger.debug(
                    "EditEventDialog._run_dialog: field_not_editable field=%s",
                    field_name,
                )
                continue

            attr = self.event.editable_attributes[field_name]
            if await self._edit_custom_field(field_name):
                continue
            if self._is_bool_field(attr):
                await self._edit_bool_field(field_name)
            else:
                await self._edit_text_field(field_name)

    def _is_bool_field(self, attr: EditableAttribute) -> bool:
        """Check if an attribute is a boolean type."""
        if attr.field_type == bool:
            return True
        if isinstance(attr.field_type, tuple) and bool in attr.field_type:
            return True
        return False

    def _get_field_display_value(self, field_name: str) -> str:
        """Get the display value for a field (staged edit or event)."""
        if field_name in self._staged_edits:
            return str(self._staged_edits[field_name])
        return str(self.event.get(field_name))

    def _build_field_choices(self, context: dict[str, Any]) -> list[tuple[str, str]]:
        """Build choices list for field selection dialog.

        Args:
            context: Dialog context (passed by ChoiceDialog, unused).
        """
        choices: list[tuple[str, str]] = []
        for name in self.event.editable_attributes:
            display_value = self._get_field_display_value(name)
            label = f"{name}: {display_value}"
            choices.append((label, name))
        choices.append(("Done", DONE_CALLBACK))
        return choices

    def _get_field_list_prompt(self) -> str:
        """Build the prompt text for field list screen."""
        event_name = self.event.event_name
        return f'Editing "{event_name}". Select field:'

    def _validate_and_stage_value(
        self,
        field_name: str,
        parsed_value: Any,
    ) -> tuple[bool, str | None]:
        """Validate a parsed value and stage it in ``_staged_edits`` if valid.

        Args:
            field_name: Name of the field being edited.
            parsed_value: The parsed value to validate and stage.

        Returns:
            (success, error_message) — error_message is None on success.
        """
        attr = self.event.editable_attributes[field_name]

        is_valid, error = attr.validate(parsed_value)
        if not is_valid:
            return False, error

        old_value = self._staged_edits.get(field_name)
        self._staged_edits[field_name] = parsed_value

        if self.validator:
            is_valid, error = self.validator(self._staged_edits)
            if not is_valid:
                if old_value is not None:
                    self._staged_edits[field_name] = old_value
                else:
                    del self._staged_edits[field_name]
                return False, error

        return True, None

    def _apply_all_edits(self) -> None:
        """Apply all staged edits to the event."""
        for field_name, value in self._staged_edits.items():
            self.event.edit(field_name, value)
        self.event.edited = True

    async def _edit_custom_field(self, field_name: str) -> bool:
        """Handle editing of a field with a custom dialog.

        Called in the edit loop after verifying the field exists in
        editable_attributes, but before the default bool/text dispatch.
        Subclasses override this to launch a custom dialog for specific
        fields (e.g., a list editor instead of a text input).

        Args:
            field_name: Name of the editable attribute selected by the user.

        Returns:
            True if the field was handled by a custom editor (the loop
            continues to the next field selection). False to fall through
            to the default bool/text editing.
        """
        get_logger().debug(
            "EditEventDialog._edit_custom_field: fallthrough field=%s (no custom handler)",
            field_name,
        )
        return False

    async def _edit_bool_field(self, field_name: str) -> bool:
        """Edit a boolean field using ConfirmDialog.

        Args:
            field_name: Name of the boolean field to edit.

        Returns:
            True if field was successfully edited, False if cancelled.
        """
        logger = get_logger()
        logger.debug("EditEventDialog._edit_bool_field: editing field=%s", field_name)
        current = self._get_field_display_value(field_name)

        while True:
            bool_dialog = create_confirm_dialog(
                prompt=f"Set {field_name} to True? (current: {current})",
                keyboard_type=self.keyboard_type,
                yes_label="True",
                no_label="False",
                include_cancel=True,
            )
            result = await bool_dialog.start(self.context)

            if is_cancelled(result):
                logger.info("EditEventDialog._edit_bool_field: cancelled field=%s", field_name)
                return False

            new_value = result
            success, error = self._validate_and_stage_value(field_name, new_value)

            if success:
                logger.info(
                    "EditEventDialog._edit_bool_field: staged field=%s value=%s",
                    field_name,
                    new_value,
                )
                return True

            logger.info(
                "EditEventDialog._edit_bool_field: validation_failed field=%s error=%s",
                field_name,
                error,
            )
            await get_app().send_messages(f"\u26a0\ufe0f {error}")

    async def _edit_text_field(self, field_name: str) -> bool:
        """Edit a text field using UserInputDialog.

        Args:
            field_name: Name of the text field to edit.

        Returns:
            True if field was successfully edited, False if cancelled.
        """
        logger = get_logger()
        logger.debug("EditEventDialog._edit_text_field: editing field=%s", field_name)
        attr = self.event.editable_attributes[field_name]

        def make_validator() -> Callable[[str], tuple[bool, str]]:
            """Create a validator that parses and validates the input."""
            def validator(text: str) -> tuple[bool, str]:
                try:
                    parsed_value = attr.parse(text)
                except (ValueError, TypeError) as e:
                    error = str(e) if str(e) else "Invalid input"
                    get_logger().debug(
                        "EditEventDialog._edit_text_field: parse_failed field=%s error=%s",
                        field_name,
                        error,
                        exc_info=True,
                    )
                    return False, error

                is_valid, error = attr.validate(parsed_value)
                if not is_valid:
                    return False, error

                if self.validator:
                    old_value = self._staged_edits.get(field_name)
                    self._staged_edits[field_name] = parsed_value
                    is_valid, error = self.validator(self._staged_edits)
                    if old_value is not None:
                        self._staged_edits[field_name] = old_value
                    else:
                        self._staged_edits.pop(field_name, None)
                    if not is_valid:
                        return False, error

                return True, ""
            return validator

        current = self._get_field_display_value(field_name)
        text_dialog = UserInputDialog(
            prompt=f"Enter new value for {field_name} (current: {current}):",
            validator=make_validator(),
            include_cancel=True,
            keyboard_type=self.keyboard_type,
        )
        result = await text_dialog.start(self.context)

        if is_cancelled(result):
            logger.info("EditEventDialog._edit_text_field: cancelled field=%s", field_name)
            return False

        if not isinstance(result, str):
            logger.debug(
                "EditEventDialog._edit_text_field: unexpected_result_type field=%s result_type=%s",
                field_name,
                type(result).__name__,
            )
            return False
        parsed_value = attr.parse(result)
        self._staged_edits[field_name] = parsed_value
        logger.info(
            "EditEventDialog._edit_text_field: staged field=%s value=%s",
            field_name,
            parsed_value,
        )
        return True

    def reset(self) -> None:
        """Reset the dialog for reuse."""
        super().reset()
        self._staged_edits = {}
        get_logger().debug("EditEventDialog.reset: reset staged_edits cleared")
