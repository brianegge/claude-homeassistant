"""HTTP API endpoints for the Claude Agent integration."""

from __future__ import annotations

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .agent_runner import run_agent
from .const import DOMAIN


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


def async_register_http(hass: HomeAssistant) -> None:
    """Register HTTP views for the integration."""
    hass.http.register_view(ClaudeAgentChatView)
