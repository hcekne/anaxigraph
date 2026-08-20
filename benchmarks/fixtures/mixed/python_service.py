"""Python member of the mixed-language extraction fixture."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Greeting:
    message: str


def greet(name: str) -> Greeting:
    return Greeting(message=f"Hello, {name}")
