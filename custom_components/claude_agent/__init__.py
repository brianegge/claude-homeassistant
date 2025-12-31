"""Claude Agent integration for Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    DATA_PANEL_REGISTERED,
    DEFAULT_MODEL,
    DOMAIN,
    PANEL_FILENAME,
    PANEL_ICON,
    PANEL_STATIC_PATH,
    PANEL_TITLE,
    PANEL_URL_PATH,
)
from .websocket_api import async_register as async_register_websocket


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Claude Agent integration."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_PANEL_REGISTERED, False)

    async_register_websocket(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Claude Agent from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"entry": entry}

    await _register_panel(hass)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to the latest version."""
    if entry.version == 1:
        data = {**entry.data}
        if data.get("model") in (None, "", "claude-3-5-sonnet"):
            data["model"] = DEFAULT_MODEL
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def _register_panel(hass: HomeAssistant) -> None:
    """Register the custom panel if it hasn't been registered yet."""
    if hass.data.get(DOMAIN, {}).get(DATA_PANEL_REGISTERED):
        return

    panel_path = Path(__file__).parent / "frontend" / PANEL_FILENAME
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=PANEL_STATIC_PATH,
                path=str(panel_path),
                cache_headers=False,
            )
        ]
    )

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name="claude-agent-panel",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=PANEL_STATIC_PATH,
        require_admin=True,
        config_panel_domain=DOMAIN,
    )

    hass.data[DOMAIN][DATA_PANEL_REGISTERED] = True
