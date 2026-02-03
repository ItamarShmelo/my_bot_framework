"""Editable attribute system for runtime-configurable parameters.

This module provides:
- EditableAttribute: Core class for typed, validated, editable values
- EditableMixin: Mixin for objects with editable attributes
"""

from abc import ABC
from typing import Any, Callable, List, Optional, Tuple, Union

from .accessors import get_logger


# =============================================================================
# Helper functions for factory methods
# =============================================================================


def _is_none_string(s: str, include_empty: bool = True) -> bool:
    """Check if a string represents None.
    
    Args:
        s: The string to check.
        include_empty: If True, treat empty string as None.
    
    Returns:
        True if the string represents None.
    """
    s_lower = s.strip().lower()
    if include_empty:
        return s_lower in ("none", "null", "")
    return s_lower in ("none", "null")


def _make_numeric_validator(
    positive: bool,
    min_val: Optional[Union[int, float]],
    max_val: Optional[Union[int, float]],
) -> Callable[[Optional[Union[int, float]]], Tuple[bool, str]]:
    """Create a validator for numeric types (int/float).
    
    Args:
        positive: If True, value must be > 0.
        min_val: Minimum allowed value (inclusive).
        max_val: Maximum allowed value (inclusive).
    
    Returns:
        A validator function that returns (is_valid, error_message).
    """
    def validator(v: Optional[Union[int, float]]) -> Tuple[bool, str]:
        if v is None:
            return True, ""
        if positive and v <= 0:
            return False, "Must be positive"
        if min_val is not None and v < min_val:
            return False, f"Must be >= {min_val}"
        if max_val is not None and v > max_val:
            return False, f"Must be <= {max_val}"
        return True, ""
    
    return validator


class EditableAttribute:
    """A runtime-editable attribute with parsing and validation.
    
    - `parse`: User-provided callable that receives string, returns typed value
    - `value` property: getter returns typed value, setter parses strings and validates
    - `validator`: Optional function that receives typed value, returns (is_valid, error_msg)
    
    Factory methods provide convenient constructors for common types:
    - EditableAttribute.float("name", 1.0, positive=True)
    - EditableAttribute.int("count", 10, min_val=0, max_val=100)
    - EditableAttribute.bool("enabled", True)
    - EditableAttribute.str("mode", "auto", choices=["auto", "manual"])
    - EditableAttribute.float("limit", None, optional=True)  # allows None
    """

    def __init__(
        self,
        name: str,
        field_type: type,
        initial_value: Any,
        parse: Callable[[str], Any],
        validator: Optional[Callable[[Any], Tuple[bool, str]]] = None,
    ) -> None:
        """Initialize an editable attribute.
        
        Args:
            name: Attribute name (used for identification).
            field_type: Expected type(s) for the value. Can be a single type
                or tuple of types (e.g., (int, type(None)) for optional int).
            initial_value: Starting value (must match field_type).
            parse: Function that converts a string input to the typed value.
            validator: Optional function that validates the typed value.
                Receives the value and returns (is_valid: bool, error_msg: str).
        """
        self.name = name
        self.field_type = field_type
        self._value = initial_value
        self.parse = parse
        self.validator = validator

    def validate(self, value: Any) -> Tuple[bool, str]:
        """Validate a typed value. Returns (is_valid, error_message)."""
        # Type check - field_type can be a single type or tuple of types
        if not isinstance(value, self.field_type):
            if isinstance(self.field_type, tuple):
                type_names = " or ".join(t.__name__ for t in self.field_type)
            else:
                type_names = self.field_type.__name__
            return False, f"Expected {type_names}, got {type(value).__name__}"

        # Custom validator
        if self.validator:
            return self.validator(value)

        return True, ""

    @property
    def value(self) -> Any:
        """Get the current value."""
        return self._value

    @value.setter
    def value(self, new_value: Any) -> None:
        """Set value - parses if string, then validates. Raises ValueError if invalid."""
        # If string, parse first
        if isinstance(new_value, str):
            new_value = self.parse(new_value)

        # Validate the (parsed) value
        is_valid, error = self.validate(new_value)
        if not is_valid:
            raise ValueError(error)
        self._value = new_value

    # =========================================================================
    # Factory methods for common types
    # =========================================================================

    @classmethod
    def float(
        cls,
        name: str,
        initial_value: Optional[float],
        *,
        positive: bool = False,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        optional: bool = False,
    ) -> "EditableAttribute":
        """Create a float attribute with optional constraints.
        
        Args:
            name: Attribute name.
            initial_value: Starting value (can be None if optional=True).
            positive: If True, value must be > 0.
            min_val: Minimum allowed value (inclusive).
            max_val: Maximum allowed value (inclusive).
            optional: If True, allows None values. Parses "none", "null", "" as None.
        
        Examples:
            EditableAttribute.float("rate", 1.0, positive=True)
            EditableAttribute.float("scale", 0.5, min_val=0.0, max_val=1.0)
            EditableAttribute.float("limit", None, optional=True, positive=True)
        """
        def parse_float(s: str) -> Optional[float]:
            if optional and _is_none_string(s, include_empty=True):
                return None
            return float(s)
        
        return cls(
            name=name,
            field_type=(float, type(None)) if optional else float,
            initial_value=initial_value,
            parse=parse_float,
            validator=_make_numeric_validator(positive, min_val, max_val),
        )

    @classmethod
    def int(
        cls,
        name: str,
        initial_value: Optional[int],
        *,
        positive: bool = False,
        min_val: Optional[int] = None,
        max_val: Optional[int] = None,
        optional: bool = False,
    ) -> "EditableAttribute":
        """Create an int attribute with optional constraints.
        
        Args:
            name: Attribute name.
            initial_value: Starting value (can be None if optional=True).
            positive: If True, value must be > 0.
            min_val: Minimum allowed value (inclusive).
            max_val: Maximum allowed value (inclusive).
            optional: If True, allows None values. Parses "none", "null", "" as None.
        
        Examples:
            EditableAttribute.int("count", 10, positive=True)
            EditableAttribute.int("threshold", 90, min_val=0, max_val=100)
            EditableAttribute.int("max_items", None, optional=True, min_val=1)
        """
        def parse_int(s: str) -> Optional[int]:
            if optional and _is_none_string(s, include_empty=True):
                return None
            return int(s)
        
        return cls(
            name=name,
            field_type=(int, type(None)) if optional else int,
            initial_value=initial_value,
            parse=parse_int,
            validator=_make_numeric_validator(positive, min_val, max_val),
        )

    @classmethod
    def bool(
        cls,
        name: str,
        initial_value: Optional[bool],
        *,
        optional: bool = False,
    ) -> "EditableAttribute":
        """Create a boolean attribute.
        
        Parses common boolean strings: true/false, yes/no, 1/0, on/off.
        
        Args:
            name: Attribute name.
            initial_value: Starting value (can be None if optional=True).
            optional: If True, allows None values. Parses "none", "null" as None.
        
        Examples:
            EditableAttribute.bool("enabled", True)
            EditableAttribute.bool("override", None, optional=True)
        """
        def parse_bool(s: str) -> Optional[bool]:
            if optional and _is_none_string(s, include_empty=False):
                return None
            s_lower = s.strip().lower()
            if s_lower in ("true", "yes", "1", "on"):
                return True
            if s_lower in ("false", "no", "0", "off"):
                return False
            raise ValueError(f"Cannot parse '{s}' as boolean")
        
        return cls(
            name=name,
            field_type=(bool, type(None)) if optional else bool,
            initial_value=initial_value,
            parse=parse_bool,
            validator=None,
        )

    @classmethod
    def str(
        cls,
        name: str,
        initial_value: Optional[str],
        *,
        choices: Optional[List[str]] = None,
        optional: bool = False,
    ) -> "EditableAttribute":
        """Create a string attribute with optional choices validation.
        
        Args:
            name: Attribute name.
            initial_value: Starting value (can be None if optional=True).
            choices: If provided, value must be one of these strings.
            optional: If True, allows None values. Parses "none", "null" as None.
        
        Examples:
            EditableAttribute.str("mode", "auto", choices=["auto", "manual"])
            EditableAttribute.str("label", "default")
            EditableAttribute.str("prefix", None, optional=True, choices=["A", "B"])
        """
        def parse_str(s: str) -> Optional[str]:
            if optional and _is_none_string(s, include_empty=False):
                return None
            return s
        
        def validator(v: Optional[str]) -> Tuple[bool, str]:
            if v is None:
                return True, ""
            if choices is not None and v not in choices:
                return False, f"Must be one of: {', '.join(choices)}"
            return True, ""
        
        has_validator = choices is not None or optional
        return cls(
            name=name,
            field_type=(str, type(None)) if optional else str,
            initial_value=initial_value,
            parse=parse_str,
            validator=validator if has_validator else None,
        )


class EditableMixin(ABC):
    """Mixin for objects with runtime-editable attributes.
    
    The `edited` property allows signaling that parameters have changed,
    triggering immediate re-processing in events that support it.
    """
    
    _edited: bool = False

    @property
    def editable_attributes(self) -> dict[str, "EditableAttribute"]:
        """Mapping of editable attributes."""
        if not hasattr(self, "_editable_attributes"):
            self._editable_attributes = {}
        return self._editable_attributes

    @editable_attributes.setter
    def editable_attributes(self, attributes: List["EditableAttribute"]) -> None:
        """Initialize the editable attribute mapping with validation."""
        self._init_editable_attributes(attributes)

    def _init_editable_attributes(self, attributes: List["EditableAttribute"]) -> None:
        """Validate and store editable attributes."""
        if not isinstance(attributes, list):
            raise TypeError("attributes must be a list of EditableAttribute")
        mapping: dict[str, EditableAttribute] = {}
        for attribute in attributes:
            if not isinstance(attribute, EditableAttribute):
                raise TypeError("All attributes must be EditableAttribute instances")
            if not isinstance(attribute.name, str) or not attribute.name:
                raise ValueError("EditableAttribute.name must be a non-empty string")
            if attribute.name in mapping:
                raise ValueError(f"Duplicate EditableAttribute name: {attribute.name}")
            mapping[attribute.name] = attribute
        self._editable_attributes = mapping

    @property
    def edited(self) -> bool:
        """Check if the object has been marked as edited."""
        return self._edited

    @edited.setter
    def edited(self, value: bool) -> None:
        """Set the edited flag."""
        logger = get_logger()
        logger.info("[%s] edited_flag_set value=%s", type(self).__name__, value)
        self._edited = value

    def edit(self, name: str, value: Any) -> None:
        """Edit an attribute by name (fail fast if missing)."""
        if name not in self.editable_attributes:
            raise KeyError(f"Unknown editable attribute: {name}")
        self.editable_attributes[name].value = value
        self.edited = True
    
    def get(self, name: str) -> Any:
        """Get an attribute value by name (fail fast if missing)."""
        if name not in self.editable_attributes:
            raise KeyError(f"Unknown editable attribute: {name}")
        return self.editable_attributes[name].value


