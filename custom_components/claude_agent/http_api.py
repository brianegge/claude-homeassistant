"""HTTP API endpoints for the Claude Agent integration."""

from __future__ import annotations

import shutil
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry, device_registry, entity_registry

from .agent_runner import run_agent
from .const import DOMAIN

try:
    import claude_agent_sdk as CLAUDE_AGENT_SDK  # pylint: disable=import-error
except Exception:  # pragma: no cover - depends on runtime env
    CLAUDE_AGENT_SDK = None


def _find_cli_path(cli_path: str | None) -> tuple[bool, str | None, str | None]:
    if cli_path:
        path = Path(cli_path).expanduser()
        if path.exists():
            return True, str(path), None
        return False, None, f"cli_path not found: {path}"

    if CLAUDE_AGENT_SDK is not None:
        pkg_dir = Path(CLAUDE_AGENT_SDK.__file__).resolve().parent
        for name in ("claude", "claude.exe"):
            bundled = pkg_dir / "_bundled" / name
            if bundled.exists():
                return True, str(bundled), None

    if cli := shutil.which("claude"):
        return True, cli, None

    return False, None, "Claude Code CLI not found."


def _get_config_entry(hass: HomeAssistant):
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


class ClaudeAgentChatView(HomeAssistantView):
    """Handle chat requests for the Claude Agent panel."""

    url = "/api/claude_agent/chat"
    name = "api:claude_agent:chat"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST requests for chat generation."""
        hass: HomeAssistant = request.app["hass"]
        try:
            data = await request.json()
        except Exception as err:
            return web.json_response({"error": f"Invalid JSON: {err}"}, status=400)

        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"error": "Missing prompt."}, status=400)

        target = data.get("target", "automations.yaml")
        if target != "automations.yaml":
            return web.json_response(
                {"error": "Only automations.yaml is supported for now."}, status=400
            )

        entry = _get_config_entry(hass)
        if entry is None:
            return web.json_response(
                {"error": "No Claude Agent config entry found."}, status=400
            )

        try:
            result = await run_agent(hass, entry_data=entry.data, prompt=prompt)
        except HomeAssistantError as err:
            return web.json_response({"error": str(err)}, status=400)
        except Exception as err:
            return web.json_response({"error": str(err)}, status=500)

        return web.json_response(
            {
                "updated_yaml": result.updated_yaml,
                "summary": result.summary,
                "warnings": result.validation.warnings,
            }
        )


class ClaudeAgentStatusView(HomeAssistantView):
    """Return backend capability status for the panel."""

    url = "/api/claude_agent/status"
    name = "api:claude_agent:status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Report CLI availability and registry counts."""
        hass: HomeAssistant = request.app["hass"]
        entry = _get_config_entry(hass)
        cli_path = entry.data.get("cli_path") if entry else None
        cli_ok, cli_resolved, cli_error = _find_cli_path(cli_path)

        try:
            entities = entity_registry.async_get(hass).entities
            devices = device_registry.async_get(hass).devices
            areas = area_registry.async_get(hass).areas
            registry_info = {
                "entities": len(entities),
                "devices": len(devices),
                "areas": len(areas),
                "source": "api",
            }
        except Exception as err:
            storage_dir = Path(hass.config.path(".storage"))
            registry_info = {
                "entities": 0,
                "devices": 0,
                "areas": 0,
                "source": "storage",
                "error": str(err),
                "storage_path": str(storage_dir),
            }

        return web.json_response(
            {
                "cli": {
                    "available": cli_ok,
                    "path": cli_resolved,
                    "error": cli_error,
                },
                "registries": registry_info,
            }
        )


def async_register_http(hass: HomeAssistant) -> None:
    """Register HTTP views for the integration."""
    hass.http.register_view(ClaudeAgentChatView)
    hass.http.register_view(ClaudeAgentStatusView)
