# Native Home Assistant Integration Architecture (Claude Agent)

## Goal
Provide a first-class Home Assistant experience: a native panel UI that can draft and apply automations, backed by HA-safe validation and guarded file writes.

## Core Components
- Custom integration (`custom_components/claude_agent`)
- Sidebar panel (custom panel served as a JS module)
- WebSocket API for UI <-> backend communication
- Config entry for Claude credentials and model settings

## Data Flow (Automations MVP)
1. User opens the "Claude Agent" panel.
2. Panel calls WebSocket endpoints to read `automations.yaml`.
3. Agent (future step) proposes YAML changes.
4. Backend validates and writes to `automations.yaml`.
5. HA reloads automations (future step).

## Guardrails
- Allowlist file access (automations-only in MVP).
- Read/write happens via `hass.config.path()` so all access stays inside `/config`.
- Writes are atomic to avoid partial files.
- Panel requires admin access.

## Backend WebSocket API (MVP)
- `claude_agent/get_info` -> return config paths for UI display
- `claude_agent/get_automations` -> return content of `automations.yaml`
- `claude_agent/write_automations` -> write updated YAML content

## Planned Validation Layer (Next)
- Replace `.storage` parsing with HA registries:
  - `entity_registry`, `device_registry`, `area_registry`
- Use HA config check service or internal validation helpers.
- Block write/apply on validation errors and return structured errors to UI.

## Minimal Prototype Skeleton
- Panel loads a JS module served by the integration.
- Buttons to load/save `automations.yaml` over WebSocket.
- No external dependencies and no Supervisor add-on required.

## Next Steps
- Add diff preview and explicit "Apply" step.
- Add validation + reload endpoints.
- Integrate Claude Agent SDK (network calls only).
- Extend to scripts/scenes after automations are stable.
