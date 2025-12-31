"""Anthropic API client for the Claude Agent integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1024
ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class ToolResponse:
    """Structured response for tool-using Anthropic calls."""

    text: str
    tool_input: dict[str, Any]


def _extract_text(data: dict[str, Any]) -> str:
    content = data.get("content", [])
    if isinstance(content, str):
        return content

    texts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)

    return "".join(texts)


def _extract_tool_input(data: dict[str, Any], tool_name: str) -> dict[str, Any]:
    content = data.get("content", [])
    if not isinstance(content, list):
        raise HomeAssistantError("Anthropic response did not include tool output.")

    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == tool_name
        ):
            input_data = block.get("input", {})
            if not isinstance(input_data, dict):
                raise HomeAssistantError("Anthropic tool input is not an object.")
            return input_data

    raise HomeAssistantError(
        f"Anthropic response did not include tool output for {tool_name}."
    )


async def _post_message(
    hass: HomeAssistant,
    *,
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not api_key:
        raise HomeAssistantError("Anthropic API key is missing.")

    url = f"{base_url.rstrip('/')}/v1/messages"
    session = async_get_clientsession(hass)
    async with session.post(
        url,
        json=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    ) as response:
        if response.status < 200 or response.status >= 300:
            body = await response.text()
            raise HomeAssistantError(f"Anthropic API error {response.status}: {body}")

        try:
            data = await response.json()
        except Exception as err:  # pragma: no cover - depends on remote response
            body = await response.text()
            raise HomeAssistantError(
                f"Anthropic API returned invalid JSON: {body}"
            ) from err

    return data


async def create_message(
    hass: HomeAssistant,
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Create an Anthropic message and return the concatenated text output."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
    }
    if system:
        payload["system"] = system

    _LOGGER.debug(
        "Anthropic request prepared: model=%s base_url=%s max_tokens=%s",
        model,
        base_url,
        payload["max_tokens"],
    )
    data = await _post_message(
        hass,
        api_key=api_key,
        base_url=base_url,
        payload=payload,
    )
    return _extract_text(data)


async def create_message_with_tools(
    hass: HomeAssistant,
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tool_name: str,
    tools: list[dict[str, Any]],
    tool_choice: dict[str, Any],
    system: str | None = None,
    max_tokens: int | None = None,
) -> ToolResponse:
    """Create an Anthropic message with tools and return tool input."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
    }
    if system:
        payload["system"] = system

    _LOGGER.debug(
        "Anthropic tool request prepared: model=%s base_url=%s tool=%s max_tokens=%s",
        model,
        base_url,
        tool_name,
        payload["max_tokens"],
    )

    data = await _post_message(
        hass,
        api_key=api_key,
        base_url=base_url,
        payload=payload,
    )
    return ToolResponse(
        text=_extract_text(data),
        tool_input=_extract_tool_input(data, tool_name),
    )
