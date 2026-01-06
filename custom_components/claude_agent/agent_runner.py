"""Agent SDK runner for automation updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (  # pylint: disable=import-error
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .agent_tools import ToolState, create_agent_tool_server
from .automation_validation import ValidationResult, validate_automations_yaml
from .const import DEFAULT_MODEL

MCP_SERVER_ALIAS = "claude_agent"
MAX_TURNS = 4


@dataclass
class AgentResult:
    """Result of an agent run."""

    updated_yaml: str
    summary: str
    validation: ValidationResult


def _build_system_prompt() -> str:
    return (
        "You are updating Home Assistant automations.yaml. "
        "Always call read_automations to get the current file. "
        "Then call propose_updated_automations with the full updated YAML. "
        "Finally call validate_automations_yaml with the updated YAML. "
        "Do not write files or include Markdown fences."
    )


def _build_allowed_tools() -> list[str]:
    prefix = f"mcp__{MCP_SERVER_ALIAS}__"
    return [
        f"{prefix}read_automations",
        f"{prefix}propose_updated_automations",
        f"{prefix}validate_automations_yaml",
    ]


def _build_env(entry_data: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    api_key = entry_data.get("api_key", "")
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
        env["CLAUDE_API_KEY"] = api_key
    base_url = entry_data.get("base_url", "")
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    return env


async def run_agent(
    hass: HomeAssistant, *, entry_data: dict[str, Any], prompt: str
) -> AgentResult:
    """Run the Claude Agent SDK to propose updated automations YAML."""
    state = ToolState()
    server = create_agent_tool_server(hass, state)
    options = ClaudeAgentOptions(
        model=entry_data.get("model", DEFAULT_MODEL),
        system_prompt=_build_system_prompt(),
        mcp_servers={MCP_SERVER_ALIAS: server},
        allowed_tools=_build_allowed_tools(),
        max_turns=MAX_TURNS,
        cwd=hass.config.path(),
        cli_path=entry_data.get("cli_path") or None,
        env=_build_env(entry_data),
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for _ in client.receive_response():
                pass
    except (
        CLINotFoundError,
        CLIConnectionError,
        CLIJSONDecodeError,
        ProcessError,
    ) as err:
        raise HomeAssistantError(f"Claude Agent SDK error: {err}") from err
    except ClaudeSDKError as err:
        raise HomeAssistantError(f"Claude Agent SDK error: {err}") from err
    except Exception as err:
        raise HomeAssistantError(f"Claude Agent SDK failed: {err}") from err

    if not state.updated_yaml or not state.updated_yaml.strip():
        raise HomeAssistantError("Agent did not return updated YAML.")

    validation = validate_automations_yaml(hass, state.updated_yaml)
    if validation.errors:
        raise HomeAssistantError("Validation failed: " + "; ".join(validation.errors))

    return AgentResult(
        updated_yaml=state.updated_yaml,
        summary=state.summary or "",
        validation=validation,
    )
