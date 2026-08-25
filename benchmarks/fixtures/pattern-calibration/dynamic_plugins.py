"""A registry-driven plugin boundary whose implementations look unused to static calls."""

from collections.abc import Callable

Plugin = Callable[[str], str]
PLUGINS: dict[str, Plugin] = {}


def plugin(name: str):
    def register(function: Plugin) -> Plugin:
        PLUGINS[name] = function
        return function

    return register


@plugin("upper")
def uppercase(value: str) -> str:
    return value.upper()


@plugin("slug")
def slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def execute(configured_name: str, value: str) -> str:
    return PLUGINS[configured_name](value)
