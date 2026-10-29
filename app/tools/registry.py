"""
Central tool registry — registers all Claude tools and dispatches calls.

Add a new tool by implementing a function and decorating it with @registry.tool().
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import structlog

from app.models.call import CallSession

log = structlog.get_logger()


class ToolRegistry:
    _tools: dict[str, dict] = {}
    _handlers: dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str, description: str, input_schema: dict):
        """Decorator factory to register a tool handler."""

        def decorator(fn: Callable):
            cls._tools[name] = {
                "name": name,
                "description": description,
                "input_schema": input_schema,
            }
            cls._handlers[name] = fn
            return fn

        return decorator

    def get_schemas(self) -> list[dict]:
        return list(self._tools.values())

    async def call(self, name: str, args: dict, session: CallSession) -> Any:
        handler = self._handlers.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        return await handler(args, session)


# Eagerly import tool modules so decorators run
def _load_tools():
    modules = [
        "app.tools.calendar_tool",
        "app.tools.crm_tool",
        "app.tools.knowledge_base",
        "app.tools.transfer_tool",
        "app.tools.call_control",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as e:
            log.warning("tool.load_failed", module=mod, error=str(e))


_load_tools()
