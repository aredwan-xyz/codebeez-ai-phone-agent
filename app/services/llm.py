"""
Claude LLM service with streaming + tool use.

Streams text tokens as they arrive so TTS can start immediately.
Tool results are injected back into the conversation and streaming resumes.
"""

import asyncio
import json
from collections.abc import AsyncGenerator

import anthropic
import structlog

from app.config import get_settings
from app.models.call import CallSession
from app.models.conversation import Message, Role
from app.tools.registry import ToolRegistry

log = structlog.get_logger()
settings = get_settings()


def _to_anthropic_messages(messages: list[Message]) -> tuple[str | None, list[dict]]:
    """Split system message out and convert to Anthropic message format."""
    system = None
    msgs = []
    for m in messages:
        if m.role == Role.SYSTEM:
            system = m.content
        elif m.role == Role.USER:
            msgs.append({"role": "user", "content": m.content})
        elif m.role == Role.ASSISTANT:
            msgs.append({"role": "assistant", "content": m.content})
    return system, msgs


class LLMService:
    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._registry = ToolRegistry()

    async def stream(
        self,
        messages: list[Message],
        call_session: CallSession,
    ) -> tuple[AsyncGenerator[str, None], list[str]]:
        """
        Returns (text_generator, tools_used_list).
        Callers must await and iterate the generator.
        """
        tools_used: list[str] = []
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _run():
            system, msgs = _to_anthropic_messages(messages)
            tool_schemas = self._registry.get_schemas()

            # Agentic loop: keep going while Claude wants to use tools
            while True:
                full_response = ""
                tool_calls: list[dict] = []
                current_tool: dict | None = None

                async with self._client.messages.stream(
                    model=settings.claude_model,
                    max_tokens=settings.max_agent_tokens,
                    system=system,
                    messages=msgs,
                    tools=tool_schemas,
                ) as stream:
                    async for event in stream:
                        if hasattr(event, "type"):
                            etype = event.type

                            if etype == "content_block_start":
                                block = event.content_block
                                if block.type == "tool_use":
                                    current_tool = {
                                        "id": block.id,
                                        "name": block.name,
                                        "input_json": "",
                                    }
                            elif etype == "content_block_delta":
                                delta = event.delta
                                if delta.type == "text_delta":
                                    full_response += delta.text
                                    await queue.put(delta.text)
                                elif delta.type == "input_json_delta" and current_tool:
                                    current_tool["input_json"] += delta.partial_json
                            elif etype == "content_block_stop":
                                if current_tool:
                                    tool_calls.append(current_tool)
                                    current_tool = None
                            elif etype == "message_stop":
                                pass

                if not tool_calls:
                    break

                # Execute tools and loop back
                tool_results = []
                for tc in tool_calls:
                    tool_name = tc["name"]
                    tools_used.append(tool_name)
                    try:
                        args = json.loads(tc["input_json"] or "{}")
                        result = await self._registry.call(tool_name, args, call_session)
                        log.info("tool.called", name=tool_name, result_preview=str(result)[:80])
                    except Exception as e:
                        result = {"error": str(e)}
                        log.error("tool.error", name=tool_name, error=str(e))

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tc["id"],
                            "content": json.dumps(result),
                        }
                    )

                # Inject assistant turn + tool results
                msgs.append({"role": "assistant", "content": full_response or "(tool call)"})
                msgs.append({"role": "user", "content": tool_results})

            await queue.put(None)  # sentinel

        task = asyncio.create_task(_run())

        async def _gen() -> AsyncGenerator[str, None]:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            await task  # propagate exceptions

        return _gen(), tools_used
