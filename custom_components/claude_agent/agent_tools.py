"""Claude Agent SDK tools for Home Assistant automations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool  # pylint: disable=import-error
from homeassistant.core import HomeAssistant

from .automation_validation import ValidationResult, validate_automations_yaml


@dataclass
class ToolState:
    """Capture tool outputs for the current agent run."""

    updated_yaml: str | None = None
    summary: str | None = None
    validation: ValidationResult | None = None


def _automations_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("automations.yaml"))


def build_tools(hass: HomeAssistant, state: ToolState):
    """Build in-process SDK tools for the Claude Agent."""

    @tool(
        "read_automations",
        "Read the current automations.yaml content.",
        {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": [],
        },
    )
    async def read_automations(_: dict[str, Any]) -> dict[str, Any]:
        path = _automations_path(hass)
        if not path.exists():
            content = ""
        else:
            content = await hass.async_add_executor_job(path.read_text, "utf-8")
        return {"content": [{"type": "text", "text": content}]}

    @tool(
        "propose_updated_automations",
        "Propose the full updated automations.yaml content.",
        {"updated_yaml": str, "summary": str},
    )
    async def propose_updated_automations(args: dict[str, Any]) -> dict[str, Any]:
        updated_yaml = args.get("updated_yaml")
        summary = args.get("summary")
        if isinstance(updated_yaml, str):
            state.updated_yaml = updated_yaml
        if isinstance(summary, str):
            state.summary = summary
        return {"content": [{"type": "text", "text": "Updated YAML received."}]}

    @tool(
        "validate_automations_yaml",
        "Validate automations.yaml content using HA validators.",
        {"updated_yaml": str},
    )
    async def validate_automations_tool(args: dict[str, Any]) -> dict[str, Any]:
        updated_yaml = args.get("updated_yaml", "")
        if not isinstance(updated_yaml, str):
            return {
                "content": [{"type": "text", "text": "updated_yaml must be a string."}],
                "is_error": True,
            }
        result = validate_automations_yaml(hass, updated_yaml)
        state.validation = result
        if result.errors:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Validation errors:\n" + "\n".join(result.errors),
                    }
                ],
                "is_error": True,
            }
        if result.warnings:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": "Validation warnings:\n" + "\n".join(result.warnings),
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "Validation passed."}]}

    return [read_automations, propose_updated_automations, validate_automations_tool]


def create_agent_tool_server(hass: HomeAssistant, state: ToolState):
    """Create the SDK MCP server for Claude Agent tools."""
    tools = build_tools(hass, state)
    return create_sdk_mcp_server(name="claude-agent-tools", tools=tools)
