# Claude Code → Claude Agent SDK Transition

## Where We Started (Claude Code Workflow)

- **Local sync of HA config**: Pull Home Assistant configuration files into this repo (e.g. `config/`, `.storage/`).
- **Claude Code as the “agent”**: Open Claude Code in the repo and ask it to edit YAML directly.
- **Validation via hooks**: Pre/post tool-use hooks run validation scripts to catch YAML or HA errors before changes are accepted.
- **Entity context from files**: Claude Code reads the synced registry files (`config/.storage/core.entity_registry`, `core.device_registry`, `core.area_registry`) to understand available entities/devices/areas.

## What We’re Moving To (Claude Agent SDK Workflow)

- **No more config sync**: The HA instance already has the latest configuration and registry data; we’ll operate against that.
- **Claude Agent SDK**: Use the SDK to drive chat + tool calls that read/update `automations.yaml`.
- **Tool-based validation**: Keep the same pre/post validation scripts as tool hooks (YAML + HA validators) before accepting updates.
- **Panel UI**: The Home Assistant panel becomes the primary interface; it sends prompts to the SDK and shows generated YAML.

## Current Gap / Priority

We need the Claude Agent SDK to **know about devices and sensors** (entities, devices, areas) so the model can:

- Answer questions like “What motion sensors exist?”
- Propose correct entity IDs in automations.
- Validate against the same data the old workflow used.

This document is the basis for designing how to inject entity/device context into SDK sessions (e.g., via registry APIs, tool calls, or cached context) while preserving the existing validation hooks.
