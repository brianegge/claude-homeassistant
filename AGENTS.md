# Home Assistant Configuration and Claude Agent Integration

This file is the operational guide for Codex CLI in this repo. It captures
local config management, local HA Core dev, and the integration deployment
runbook. Keep these workflows separate.

## Scope

- Local config management (repo only): edit YAML under `config/` and validate.
- Local HA Core dev (no Docker): run a local HA web server for panel work.
- Integration runbook (`claude_agent`): deploy to the real HA instance via SSH.

## Project Layout

- `config/` - Home Assistant configuration synced from the live HA instance
- `config-local/` - Local HA Core dev config (not synced)
- `custom_components/claude_agent/` - Integration source
- `tools/` - Validation and helper scripts
- `venv/` - Python venv for validation tools
- `ha_venv/` - Python venv for local HA Core
- `temp/` - Temp workspace for scratch files or logs
- `.claude-code/` - Claude Code settings and hooks

## Local Config Management

Primary flow:

1. `make pull` - Sync latest config from HA
2. Edit YAML under `config/`
3. `make validate` - Run full validation
4. `make push` - Upload if validation passes
5. `make backup` - Snapshot current config

Validation tools:

- `python tools/run_tests.py` - Full validation suite
- `python tools/yaml_validator.py` - YAML syntax only
- `python tools/reference_validator.py` - Entity/device references
- `python tools/ha_official_validator.py` - HA official validation

Entity discovery:

- `make entities`
- `python tools/entity_explorer.py --search TERM`
- `python tools/entity_explorer.py --domain DOMAIN`
- `python tools/entity_explorer.py --area AREA`
- `python tools/entity_explorer.py --full`

Notes:

- Hooks run automatically after YAML edits and before push.
- Validation skips secrets and allows HA-specific YAML tags.
- Activate venv for tooling: `source venv/bin/activate`.
- Pre-push validation blocks broken uploads.

## Local HA Core Dev (No Docker)

Use this for panel development and WebSocket/API testing without the live HA
instance. Local HA Core acts as the web server, so you do not need the real HA
appliance for panel work. There is no separate panel dev server.

Setup + run:

1. `make ha-local-setup` - Create `ha_venv/` and `config-local/`
2. `make ha-local-run` - Start local HA Core
3. Open `http://localhost:8123/claude-agent` for the panel
4. `make ha-local-logs` - Tail logs
5. `make ha-local-check` - Validate local config

Panel dev loop:

- Edit files in `custom_components/claude_agent/frontend/`.
- Refresh `http://localhost:8123/claude-agent`.
- Use Chrome MCP DevTools to automate UI smoke tests (worked well).

Local HA notes:

- Local config lives in `config-local/` and is not pushed.
- The integration is linked into `config-local/custom_components/claude_agent`.
- Local config bootstrap is handled by `tools/ha_local_init.py`.
- Defaults: Python `python3.13`, log `temp/ha-local.log`.
- When changes require a local HA restart, restart immediately without prompting.
- Optional `.env` overrides: `HA_LOCAL_VENV`, `HA_LOCAL_CONFIG_PATH`,
  `HA_LOCAL_LOG_PATH`, `HA_LOCAL_PYTHON`, `HA_LOCAL_HA_VERSION`,
  `HA_LOCAL_CONSTRAINTS_URL`, `HA_LOCAL_EXTRA_PIP`.

## Home Assistant Integration Runbook (claude_agent)

Assumptions:

- SSH alias: `homeassistant_sf`
- Remote config path: `/config`
- Local integration: `custom_components/claude_agent`
- HA URL: `http://homeassistant.local:8123`

Deploy:

1. `ssh -o ConnectTimeout=10 homeassistant_sf "ls /config"`
2. `rsync -av --delete custom_components/claude_agent/ homeassistant_sf:/config/custom_components/claude_agent/`
3. `ssh homeassistant_sf "ha core restart"`
4. If needed: `ssh homeassistant_sf "ha core info"`

Verify:

- `ssh homeassistant_sf "ha core logs -n 300 | grep -i -A 4 -B 4 claude_agent"`
- `ssh homeassistant_sf "ls /config/custom_components/claude_agent"`

Known gotcha:

- `hass.http.register_static_path` no longer exists. Use
  `await hass.http.async_register_static_paths([StaticPathConfig(...)])`.

## Entity Naming Convention

Format: `location_room_device_sensor`

Examples:

- `binary_sensor.home_basement_motion_battery`
- `media_player.home_kitchen_sonos`
- `climate.home_living_room_heatpump`
- `lock.home_front_door_august`

Guidance:

- Ask for clarification if multiple devices match.
- Use entity explorer tools before writing automations.

## Entity Registry Domains

Tracked domains include:

- alarm_control_panel, binary_sensor, button, camera, climate
- device_tracker, event, image, light, lock, media_player
- number, person, scene, select, sensor, siren, switch
- time, tts, update, vacuum, water_heater, weather, zone

## Troubleshooting

Validation fails:

1. Fix YAML syntax errors
2. Verify entity references in `.storage/` files
3. Run validators individually
4. Check HA logs for official validation errors

SSH issues:

- `chmod 600 ~/.ssh/your_key`
- `ssh your_homeassistant_host`
- Check `~/.ssh/config`
