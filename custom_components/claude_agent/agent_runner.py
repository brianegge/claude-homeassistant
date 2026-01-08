"""Agent SDK runner for automation updates."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import (  # pylint: disable=import-error
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    ProcessError,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry, device_registry, entity_registry

from .agent_tools import ToolState, create_agent_tool_server
from .automation_validation import ValidationResult, validate_automations_yaml
from .const import DEFAULT_MODEL, DOMAIN, SESSION_CONTEXT_KEY
from .yaml_validation import HAYamlLoader

MCP_SERVER_ALIAS = "claude_agent"
MAX_TURNS = 4

LOGGER = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Result of an agent run."""

    updated_yaml: str
    summary: str
    validation: ValidationResult
    session_id: str | None = None


def _build_system_prompt() -> str:
    return (
        "You are updating Home Assistant automations.yaml. "
        "Always call read_automations to get the current file. "
        "Then call propose_updated_automations with the full updated YAML. "
        "Finally call validate_automations_yaml with the updated YAML. "
        "When the user references the last or recent automation, use the "
        "Recent automation references and YAML snippets from the context to "
        "identify it. "
        "Do not ask for clarification if there is a single recent automation. "
        "Do not write files or include Markdown fences."
    )


def _build_allowed_tools() -> list[str]:
    prefix = f"mcp__{MCP_SERVER_ALIAS}__"
    return [
        f"{prefix}read_automations",
        f"{prefix}propose_updated_automations",
        f"{prefix}validate_automations_yaml",
    ]


def _parse_automations(content: str) -> list[dict[str, Any]]:
    try:
        data = yaml.load(content, Loader=HAYamlLoader)
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _automation_key(item: dict[str, Any]) -> str:
    if item.get("id"):
        return f"id:{item.get('id')}"
    if item.get("alias"):
        return f"alias:{item.get('alias')}"
    return f"hash:{hash(str(item))}"


def _find_changed_automations(
    before_yaml: str, after_yaml: str
) -> list[dict[str, str]]:
    before_items = _parse_automations(before_yaml)
    after_items = _parse_automations(after_yaml)
    before_map = {_automation_key(item): item for item in before_items}
    changed: list[dict[str, str]] = []

    for item in after_items:
        key = _automation_key(item)
        if key not in before_map or before_map[key] != item:
            changed.append(
                {
                    "id": str(item.get("id") or ""),
                    "alias": str(item.get("alias") or ""),
                }
            )
    return changed


def _find_changed_items(before_yaml: str, after_yaml: str) -> list[dict[str, Any]]:
    before_items = _parse_automations(before_yaml)
    after_items = _parse_automations(after_yaml)
    before_map = {_automation_key(item): item for item in before_items}
    changed: list[dict[str, Any]] = []

    for item in after_items:
        key = _automation_key(item)
        if key not in before_map or before_map[key] != item:
            changed.append(item)
    return changed


def _merge_recent_items(
    existing: list[dict[str, Any]] | None,
    new_items: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    existing_items = existing or []
    combined = new_items + existing_items
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in combined:
        key = _automation_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _items_to_refs(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in items:
        ref_id = str(item.get("id") or "")
        ref_alias = str(item.get("alias") or "")
        refs.append({"id": ref_id, "alias": ref_alias})
    return refs


async def _read_automations(hass: HomeAssistant) -> str:
    automations_path = Path(hass.config.path("automations.yaml"))
    if not automations_path.exists():
        return ""
    return await hass.async_add_executor_job(automations_path.read_text, "utf-8")


def _build_context(
    hass: HomeAssistant,
    *,
    automations: str,
    working_label: str,
    recent_refs: list[dict[str, str]] | None,
    recent_items: list[dict[str, Any]] | None,
) -> str:

    entities = entity_registry.async_get(hass).entities
    devices = device_registry.async_get(hass).devices
    areas = area_registry.async_get(hass).areas
    entries = hass.config_entries.async_entries()

    entity_lines: list[str] = []
    for entry in entities.values():
        name = entry.name or entry.original_name or ""
        entity_lines.append(
            f"- {entry.entity_id} (name={name}, device_id={entry.device_id}, "
            f"area_id={entry.area_id}, disabled_by={entry.disabled_by})"
        )

    device_lines: list[str] = []
    for device in devices.values():
        device_lines.append(
            f"- {device.id} (name={device.name}, model={device.model}, "
            f"manufacturer={device.manufacturer}, area_id={device.area_id})"
        )

    area_lines = [f"- {area.id} (name={area.name})" for area in areas.values()]

    integration_lines = [
        f"- {entry.domain} (title={entry.title}, entry_id={entry.entry_id})"
        for entry in entries
    ]

    recent_lines = []
    if recent_refs:
        for ref in recent_refs:
            ref_id = ref.get("id") or ""
            ref_alias = ref.get("alias") or ""
            if ref_id or ref_alias:
                recent_lines.append(f"- id={ref_id} alias={ref_alias}")

    recent_section = (
        "Recent automations (most recent first). Use these when the user says "
        '"the last automation", "the one we just created", or similar.\n'
        f"{chr(10).join(recent_lines) if recent_lines else '- (none)'}\n\n"
    )

    recent_item_lines = []
    if recent_items:
        for item in recent_items:
            recent_item_lines.append(yaml.safe_dump(item, sort_keys=False).strip())
    recent_items_section = (
        "Recent automation YAML snippets:\n"
        f"{chr(10).join(recent_item_lines) if recent_item_lines else '- (none)'}\n\n"
    )

    return (
        "Context:\n"
        f"{working_label}:\n"
        f"{automations}\n\n"
        f"{recent_section}"
        f"{recent_items_section}"
        "Entities:\n"
        f"{chr(10).join(entity_lines) if entity_lines else '- (none)'}\n\n"
        "Devices:\n"
        f"{chr(10).join(device_lines) if device_lines else '- (none)'}\n\n"
        "Areas:\n"
        f"{chr(10).join(area_lines) if area_lines else '- (none)'}\n\n"
        "Integrations:\n"
        f"{chr(10).join(integration_lines) if integration_lines else '- (none)'}\n"
    )


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
    hass: HomeAssistant,
    *,
    entry_data: dict[str, Any],
    prompt: str,
    session_id: str | None = None,
) -> AgentResult:
    """Run the Claude Agent SDK to propose updated automations YAML."""
    state = ToolState()
    assistant_text: list[str] = []
    session_store = hass.data.setdefault(DOMAIN, {}).setdefault(SESSION_CONTEXT_KEY, {})
    session_context = session_store.get(session_id or "") or {}
    base_yaml = session_context.get("working_yaml")
    recent_items = session_context.get("recent_items")
    working_label = (
        "Working automations.yaml (unsaved draft)" if base_yaml else "Automations.yaml"
    )
    if base_yaml is None:
        base_yaml = await _read_automations(hass)
    recent_refs = session_context.get("recent_refs")
    context = _build_context(
        hass,
        automations=base_yaml,
        working_label=working_label,
        recent_refs=recent_refs,
        recent_items=recent_items,
    )
    full_prompt = f"{context}\nUser request:\n{prompt}"
    state.current_yaml = base_yaml
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
        continue_conversation=bool(session_id),
        resume=session_id,
    )
    result_session_id: str | None = None

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(full_prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            LOGGER.info("Claude tool_use: %s", block.name)
                        elif isinstance(block, ToolResultBlock):
                            LOGGER.info(
                                "Claude tool_result: %s error=%s",
                                block.tool_use_id,
                                bool(block.is_error),
                            )
                        elif isinstance(block, TextBlock):
                            LOGGER.debug("Claude text: %s", block.text)
                            if block.text:
                                assistant_text.append(block.text)
                        elif isinstance(block, ThinkingBlock):
                            LOGGER.debug("Claude thinking: %s", block.thinking)
                elif isinstance(message, ResultMessage):
                    LOGGER.info(
                        "Claude result: turns=%s error=%s cost=%s",
                        message.num_turns,
                        message.is_error,
                        message.total_cost_usd,
                    )
                    result_session_id = message.session_id
                else:
                    LOGGER.debug("Claude message: %s", type(message).__name__)
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
        summary = state.summary or "\n\n".join(assistant_text).strip()
        session_key = result_session_id or session_id
        if session_key and session_key not in session_store and base_yaml is not None:
            session_store[session_key] = {
                "working_yaml": base_yaml,
                "recent_refs": recent_refs or [],
                "recent_items": recent_items or [],
            }
        return AgentResult(
            updated_yaml="",
            summary=summary or "",
            validation=ValidationResult(),
            session_id=result_session_id,
        )

    validation = validate_automations_yaml(hass, state.updated_yaml)
    if validation.errors:
        raise HomeAssistantError("Validation failed: " + "; ".join(validation.errors))

    session_key = result_session_id or session_id
    if session_key:
        changed_items = _find_changed_items(base_yaml, state.updated_yaml)
        merged_items = _merge_recent_items(recent_items, changed_items)
        session_store[session_key] = {
            "working_yaml": state.updated_yaml,
            "recent_refs": _items_to_refs(merged_items),
            "recent_items": merged_items,
        }

    return AgentResult(
        updated_yaml=state.updated_yaml,
        summary=state.summary or "",
        validation=validation,
        session_id=result_session_id,
    )
