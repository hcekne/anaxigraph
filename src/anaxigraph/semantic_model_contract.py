"""Provider outcomes and strict reusable structured-output validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol


class SemanticAnalysisError(RuntimeError):
    """The configured semantic provider could not return a valid dossier."""

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        usage_reported: bool = False,
        output_truncated: bool = False,
    ) -> None:
        super().__init__(message)
        self.input_tokens = max(0, int(input_tokens))
        self.output_tokens = max(0, int(output_tokens))
        self.cache_read_input_tokens = max(0, int(cache_read_input_tokens))
        self.cache_creation_input_tokens = max(0, int(cache_creation_input_tokens))
        self.usage_reported = bool(usage_reported)
        self.output_truncated = output_truncated


@dataclass(frozen=True, slots=True)
class SemanticResult:
    """One validated dossier and the usage its executor reported for producing it.

    ``input_tokens`` is the whole prompt; the two cache counts are portions of it.
    ``usage_reported`` is set only when the executor returned a usage object, so a reported zero
    and an executor that said nothing are different facts rather than the same zero.
    """

    value: dict[str, Any]
    confidence: float
    evidence: tuple[str, ...]
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    usage_reported: bool = False


class SemanticProvider(Protocol):
    name: str

    def analyze(self, request: dict[str, Any]) -> SemanticResult: ...


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected == "object":
        _validate_object(value, schema, path)
        return
    if expected == "array":
        _validate_array(value, schema, path)
        return
    _validate_scalar(value, expected, path)
    _validate_constraints(value, schema, path)


def _validate_object(value: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(value, dict):
        raise SemanticAnalysisError(f"{path} must be an object")
    properties = schema.get("properties") or {}
    missing = [key for key in schema.get("required") or [] if key not in value]
    if missing:
        raise SemanticAnalysisError(
            f"{path} is missing required fields: {', '.join(sorted(missing))}"
        )
    if schema.get("additionalProperties") is False:
        unexpected = sorted(set(value) - set(properties))
        if unexpected:
            raise SemanticAnalysisError(f"{path} has unsupported fields: {', '.join(unexpected)}")
    for key, child in properties.items():
        if key in value:
            _validate_schema(value[key], child, f"{path}.{key}")


def _validate_array(value: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(value, list):
        raise SemanticAnalysisError(f"{path} must be an array")
    if "minItems" in schema and len(value) < schema["minItems"]:
        raise SemanticAnalysisError(f"{path} must contain at least {schema['minItems']} item(s)")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        raise SemanticAnalysisError(f"{path} must contain at most {schema['maxItems']} item(s)")
    child = schema.get("items") or {}
    for index, item in enumerate(value):
        _validate_schema(item, child, f"{path}[{index}]")


def _validate_scalar(value: Any, expected: Any, path: str) -> None:
    if expected == "string" and not isinstance(value, str):
        raise SemanticAnalysisError(f"{path} must be a string")
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise SemanticAnalysisError(f"{path} must be an integer")
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise SemanticAnalysisError(f"{path} must be a number")
    if expected == "number" and isinstance(value, float) and not math.isfinite(value):
        raise SemanticAnalysisError(f"{path} must be finite")
    if expected == "boolean" and not isinstance(value, bool):
        raise SemanticAnalysisError(f"{path} must be a boolean")


def _validate_constraints(value: Any, schema: dict[str, Any], path: str) -> None:
    if "enum" in schema and value not in schema["enum"]:
        raise SemanticAnalysisError(f"{path} must be one of: {', '.join(schema['enum'])}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SemanticAnalysisError(f"{path} must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SemanticAnalysisError(f"{path} must be at most {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SemanticAnalysisError(
                f"{path} must contain at least {schema['minLength']} character(s)"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SemanticAnalysisError(
                f"{path} must contain at most {schema['maxLength']} character(s)"
            )
