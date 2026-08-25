"""A justified provider abstraction with two real interchangeable implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    text: str
    provider: str


class CompletionProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str) -> Completion:
        """Return one completion or raise a provider-neutral error."""


class HostedProvider(CompletionProvider):
    def complete(self, prompt: str) -> Completion:
        return Completion(text=f"hosted:{prompt}", provider="hosted")


class LocalProvider(CompletionProvider):
    def complete(self, prompt: str) -> Completion:
        return Completion(text=f"local:{prompt}", provider="local")


def provider(name: str) -> CompletionProvider:
    implementations = {"hosted": HostedProvider, "local": LocalProvider}
    return implementations[name]()
