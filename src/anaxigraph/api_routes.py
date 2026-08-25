"""Composition of the bounded local HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from anaxigraph.api_agent_routes import agent_router
from anaxigraph.api_graph import GraphRoutes
from anaxigraph.api_history_routes import history_router
from anaxigraph.api_operations import operations_router
from anaxigraph.api_repository import repository_router
from anaxigraph.api_semantic_routes import semantic_router


def register_api_routes(app: FastAPI, context: Any) -> None:
    app.include_router(repository_router(context))
    app.include_router(semantic_router(context))
    app.include_router(GraphRoutes(context.database, context.selected_repository).router)
    app.include_router(history_router(context))
    app.include_router(agent_router(context))
    app.include_router(operations_router(context))
