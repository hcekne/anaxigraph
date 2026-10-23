"""Versioned parser call-site vocabulary shared with semantic graph readers."""

CALL_GRAPH_VERSION = "lexical-call-sites-v2"
CALLABLE_SYMBOL_KINDS = frozenset(
    {
        "function",
        "method",
        "async_function",
        "test",
        "api_endpoint",
        "event_handler",
        "react_component",
        "generator",
        "generator_function",
        "async_generator",
        "constructor",
    }
)
