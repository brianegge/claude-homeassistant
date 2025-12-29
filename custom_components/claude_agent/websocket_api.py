"""WebSocket API for Claude Agent."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant


def async_register(hass: HomeAssistant) -> None:
    """Register WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_info)
    websocket_api.async_register_command(hass, websocket_get_automations)
    websocket_api.async_register_command(hass, websocket_write_automations)


def _automations_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("automations.yaml"))


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


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
