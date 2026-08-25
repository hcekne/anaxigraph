"""Application startup and MCP lifespan composition."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import FastAPI

import anaxigraph.api_support as api_support


def application_lifespan(context: Any, *, scan_on_start: bool, mcp: Any):
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        context.history_service.recover(context.targets)
        if scan_on_start:
            await _scan_targets(context)
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield

    return lifespan


async def _scan_targets(context: Any) -> None:
    for target in context.targets:
        await asyncio.to_thread(
            api_support.RepositoryScanner(context.database).scan,
            target.path,
            config_path=target.config_path,
        )
    for target in context.targets:
        context.history_service.start(target)
        config = api_support.load_config(target.path, target.config_path)
        if config.semantic.enabled and config.semantic.refresh in {"on_scan", "periodic"}:
            context.semantic_refresh.start(target)
