# Agent SDK-Based Chat Interface Implementation Plan (Home Assistant)

## Goal
Implement a chat interface in the Home Assistant panel that uses the **Claude Agent SDK (Python)** on the backend and the **Cloud Client SDK** in the panel UI to draft updates to `automations.yaml`, while preserving the existing validation toolchain and HA-native guardrails.

## Execution Rules
- Each step must be executed by its own sub-agent.
- Each step must be verified by the sub-agent using the verification checklist provided in that step.
- Each step (or any significant change within a step) must be committed using `/prompts:commit` before moving on.

## Prerequisites
- HA host SSH alias: `homeassistant_sf`
- HA config path: `/config`
- Local integration path: `custom_components/claude_agent`
- HA URL: `http://homeassistant.local:8123`
- Integration config entry has Anthropic API key + model
- Claude Agent SDK (Python) installed via HA integration `manifest.json` requirements
- Cloud Client SDK available to the panel (bundled or vendored)

---

## Step 1: SDK Compatibility + Transport Decision
**Owner:** Sub-agent 1

### Scope
Determine how the Cloud Client SDK should communicate with the HA backend (WebSocket or HTTP streaming) and how the Python Agent SDK should be configured for this integration.

### Implementation
- Read Claude Agent SDK (Python) docs for `ClaudeSDKClient`, `ClaudeAgentOptions`, tool servers, and auth.
- Read Cloud Client SDK docs for transport expectations (HTTP/SSE/WS).
- Decide and document:
  - Whether to keep HA WebSocket transport or add a new HTTP endpoint.
  - How to map Cloud Client SDK client calls to HA endpoints.
  - How API key and model are injected into the Agent SDK.

### Verification (Sub-agent 1)
- Produce a short compatibility note (2-4 bullets) captured in this file or a temporary design note.

### Commit
- Commit immediately using `/prompts:commit` with a conventional message (chore/docs).

---

## Step 2: Backend Dependency + Config Flow
**Owner:** Sub-agent 2

### Scope
Add the Claude Agent SDK (Python) to the integration and ensure config options cover SDK needs.

### Implementation
- Add `claude-agent-sdk` to `custom_components/claude_agent/manifest.json` requirements.
- Update config flow to allow SDK-required settings (model, CLI path if needed).
- Ensure API key storage remains in the config entry.

### Verification (Sub-agent 2)
- Confirm HA loads the integration with the new dependency.
- Validate config entry migration if version changes.

### Commit
- Commit immediately using `/prompts:commit` with a conventional message (chore/feat).

---

## Step 3: Shared Validation Module (Parity with Existing Tools)
**Owner:** Sub-agent 3

### Scope
Ensure the agent SDK uses the same validators as the current tool-based flow.

### Implementation
- Extract or wrap the logic from:
  - `tools/yaml_validator.py`
  - `tools/reference_validator.py`
  - `custom_components/claude_agent/yaml_validation.py`
- Provide an integration-level validator entry point (e.g., `claude_agent.validation.validate_automations_yaml`).
- Keep behavior parity with existing CLI validators (same errors, same YAML tag handling).

### Verification (Sub-agent 3)
- Run local positive/negative validation tests on known YAML samples.
- Confirm parity with current `tools/` validators.

### Commit
- Commit immediately using `/prompts:commit` with a conventional message (feat/refactor).

---

## Step 4: Agent SDK Tool Server
**Owner:** Sub-agent 4

### Scope
Implement in-process tools for the agent, with explicit validation and no direct file writes.

### Implementation
- Create an SDK MCP server with tools:
  - `read_automations` -> returns current YAML
  - `propose_updated_automations(updated_yaml: str)` -> returns full YAML
  - `validate_automations_yaml(updated_yaml: str)` -> uses shared validators
  - Optional: `list_entities` -> reads entity registry for context
- Restrict allowed tools to these only (no `Bash`, no `Write`).

### Verification (Sub-agent 4)
- Unit-call each tool locally to ensure correct behavior and validation errors.

### Commit
- Commit immediately using `/prompts:commit` with a conventional message (feat).

---

## Step 5: Agent Runner + WebSocket Endpoint
**Owner:** Sub-agent 5

### Scope
Replace raw HTTP usage with `ClaudeSDKClient` and wire it into the `claude_agent/chat` WebSocket endpoint.

### Implementation
- Add an `agent_runner.py` that:
  - Builds `ClaudeAgentOptions` with `mcp_servers`, `allowed_tools`, and `cwd=hass.config.path()`.
  - Executes a single-turn prompt that **must** call `propose_updated_automations`.
  - Extracts tool output and validates before returning to UI.
- Update `claude_agent/chat` endpoint to call the runner and return `{updated_yaml, summary}`.
- Keep Save explicit: `write_automations` is still a separate action.

### Verification (Sub-agent 5)
- Test WS call in HA WebSocket dev tools.
- Confirm invalid YAML returns a structured error.

### Commit
- Commit immediately using `/prompts:commit` with a conventional message (feat).

---

## Step 6: Panel UI + Cloud Client SDK
**Owner:** Sub-agent 6

### Scope
Wire the panel to use the Cloud Client SDK for the Generate flow while still calling the HA backend.

### Implementation
- Bundle or vendor the Cloud Client SDK in `custom_components/claude_agent/frontend/`.
- Create a client wrapper that sends prompts to the backend transport selected in Step 1.
- Stream or render the response into the editor; retain explicit Save.

### Verification (Sub-agent 6)
- Open the panel and confirm Generate:
  - Sends prompt via Cloud Client SDK.
  - Receives updated YAML and updates the editor.
  - Shows errors from backend validation.

### Commit
- Commit immediately using `/prompts:commit` with a conventional message (feat).

---

## Step 7: End-to-End Verification (Local + HA Instance)
**Owner:** Sub-agent 7

### Scope
Verify the entire flow using local HA Core dev and (optionally) the remote HA instance.

### Local Dev
- `make ha-local-setup`
- `make ha-local-run`
- UI test in panel: prompt -> updated YAML -> Save -> Load
- `make ha-local-check`

### Remote HA (optional)
```bash
rsync -av --delete custom_components/claude_agent/ homeassistant_sf:/config/custom_components/claude_agent/
ssh homeassistant_sf "ha core restart"
ssh homeassistant_sf "ha core logs -n 300 | grep -i -A 4 -B 4 claude_agent"
```

### Verification (Sub-agent 7)
- Confirm updated YAML appears in panel after Generate.
- Confirm explicit Save persists changes.
- Confirm validators pass.

### Commit
- If any code changes were needed during verification, commit them with `/prompts:commit` before final handoff.

---

## Notes on Sub-Agent Execution
- Each sub-agent should operate only within its step scope.
- If a step requires a new file or change outside scope, stop and request instructions.
- Do not skip verification or commit instructions.

## Future Enhancements (After MVP)
- Add file selector (scripts/scenes) with allowlist.
- Add diff preview and apply confirmation.
- Add streaming responses over WebSocket if not already used.
- Add HA service reload (automation.reload, script.reload) after save.
