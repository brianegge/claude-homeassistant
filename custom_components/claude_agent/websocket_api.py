"""WebSocket API for Claude Agent."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .anthropic_client import create_message_with_tools
from .const import DEFAULT_MODEL, DOMAIN
from .yaml_validation import validate_yaml


def async_register(hass: HomeAssistant) -> None:
    """Register WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_info)
    websocket_api.async_register_command(hass, websocket_get_automations)
    websocket_api.async_register_command(hass, websocket_write_automations)
    websocket_api.async_register_command(hass, websocket_chat)


def _automations_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("automations.yaml"))


def _get_config_entry(hass: HomeAssistant) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


TOOL_NAME = "update_automations"
UPDATE_AUTOMATIONS_TOOL = {
    "name": TOOL_NAME,
    "description": "Return the full updated automations.yaml content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "updated_yaml": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["updated_yaml"],
    },
}


@websocket_api.websocket_command({vol.Required("type"): "claude_agent/get_info"})
@websocket_api.async_response
async def websocket_get_info(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return basic integration info for the panel."""
    connection.send_result(
        msg["id"],
        {
            "config_path": hass.config.path(),
            "automations_path": str(_automations_path(hass)),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "claude_agent/get_automations"})
@websocket_api.async_response
async def websocket_get_automations(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return the current automations YAML content."""
    path = _automations_path(hass)

    try:
        content = await hass.async_add_executor_job(_read_text, path)
    except Exception as err:  # pragma: no cover - error path depends on FS
        connection.send_error(msg["id"], "read_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "path": str(path),
            "exists": path.exists(),
            "content": content,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "claude_agent/write_automations",
        vol.Required("content"): str,
    }
)
@websocket_api.async_response
async def websocket_write_automations(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Write updated automations YAML content."""
    path = _automations_path(hass)
    content = msg["content"]

    try:
        await hass.async_add_executor_job(_write_text, path, content)
    except Exception as err:  # pragma: no cover - error path depends on FS
        connection.send_error(msg["id"], "write_failed", str(err))
        return

    connection.send_result(msg["id"], {"ok": True, "path": str(path)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "claude_agent/chat",
        vol.Required("prompt"): str,
        vol.Optional("target", default="automations.yaml"): str,
        vol.Optional("max_tokens"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def websocket_chat(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Run a chat request that updates a target YAML file."""
    target = msg.get("target", "automations.yaml")
    if target != "automations.yaml":
        connection.send_error(
            msg["id"],
            "invalid_target",
            "Only automations.yaml is supported for now.",
        )
        return

    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(
            msg["id"], "config_missing", "No Claude Agent config entry found."
        )
        return

    api_key = entry.data.get("api_key")
    model = entry.data.get("model", DEFAULT_MODEL)
    base_url = entry.data.get("base_url", "https://api.anthropic.com")
    max_tokens = msg.get("max_tokens")

    path = _automations_path(hass)
    try:
        current_yaml = await hass.async_add_executor_job(_read_text, path)
    except Exception as err:  # pragma: no cover - error path depends on FS
        connection.send_error(msg["id"], "read_failed", str(err))
        return

    system_prompt = (
        "Use the update_automations tool to return the full updated YAML. "
        "Preserve structure and do not include Markdown fences."
    )
    user_prompt = (
        "Current YAML:\n"
        f"```yaml\n{current_yaml}\n```\n\n"
        f"Task:\n{msg['prompt']}\n"
    )

    try:
        tool_response = await create_message_with_tools(
            hass,
            api_key=api_key,
            base_url=base_url,
            model=model,
            messages=[{"role": "user", "content": user_prompt}],
            tool_name=TOOL_NAME,
            tools=[UPDATE_AUTOMATIONS_TOOL],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            system=system_prompt,
            max_tokens=max_tokens,
        )
        updated_yaml = tool_response.tool_input.get("updated_yaml")
        summary = tool_response.tool_input.get("summary", "")
        if not isinstance(updated_yaml, str) or not updated_yaml.strip():
            raise HomeAssistantError(
                "Tool response missing required updated_yaml content."
            )
        if summary and not isinstance(summary, str):
            raise HomeAssistantError("Tool response summary must be a string.")
        validate_yaml(updated_yaml)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "chat_failed", str(err))
        return
    except Exception as err:  # pragma: no cover - defensive
        connection.send_error(msg["id"], "chat_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "updated_yaml": updated_yaml,
            "summary": summary,
            "path": str(path),
        },
    )
