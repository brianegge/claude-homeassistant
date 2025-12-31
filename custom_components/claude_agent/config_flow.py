"""Config flow for Claude Agent."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import DEFAULT_MODEL, DOMAIN


# pylint: disable=abstract-method
class ClaudeAgentConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Claude Agent."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(title="Claude Agent", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required("api_key"): str,
                vol.Optional("model", default=DEFAULT_MODEL): str,
                vol.Optional("base_url", default="https://api.anthropic.com"): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)
