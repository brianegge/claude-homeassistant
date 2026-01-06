"""Validation helpers for Home Assistant automations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry, device_registry, entity_registry

from .yaml_validation import HAYamlLoader


@dataclass
class ValidationResult:
    """Collect validation errors and warnings."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when no validation errors are present."""
        return not self.errors


class EntityReferenceValidator:
    """Validate entity/device/area references using HA registries."""

    SPECIAL_KEYWORDS = {"all", "none"}

    def __init__(self, hass: HomeAssistant, *, label: str) -> None:
        """Initialize the validator with HA config paths."""
        self._hass = hass
        self._label = label
        self._storage_dir = Path(hass.config.path(".storage"))
        self._entities: dict[str, Any] | None = None
        self._devices: dict[str, Any] | None = None
        self._areas: dict[str, Any] | None = None
        self._registry_source: str | None = None

    def _load_registries_from_api(self, result: ValidationResult) -> bool:
        """Load registries using HA APIs if available."""
        try:
            entities = entity_registry.async_get(self._hass).entities
            devices = device_registry.async_get(self._hass).devices
            areas = area_registry.async_get(self._hass).areas
        except Exception as err:
            result.warnings.append(f"{self._label}: Registry API unavailable: {err}")
            self._registry_source = "storage"
            return False

        self._entities = {
            entry.entity_id: {
                "entity_id": entry.entity_id,
                "id": entry.id,
                "disabled_by": entry.disabled_by,
            }
            for entry in entities.values()
        }
        self._devices = {entry.id: {"id": entry.id} for entry in devices.values()}
        self._areas = {entry.id: {"id": entry.id} for entry in areas.values()}
        self._registry_source = "api"
        return True

    def load_entity_registry(self, result: ValidationResult) -> dict[str, Any]:
        """Load the entity registry from HA storage."""
        if self._entities is not None:
            return self._entities
        if self._registry_source is None and self._load_registries_from_api(result):
            return self._entities or {}
        registry_file = self._storage_dir / "core.entity_registry"
        if not registry_file.exists():
            result.errors.append(f"Entity registry not found: {registry_file}")
            self._entities = {}
            return self._entities
        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
            self._entities = {
                entity["entity_id"]: entity
                for entity in data.get("data", {}).get("entities", [])
            }
        except Exception as err:
            result.errors.append(f"Failed to load entity registry: {err}")
            self._entities = {}
        return self._entities

    def load_device_registry(self, result: ValidationResult) -> dict[str, Any]:
        """Load the device registry from HA storage."""
        if self._devices is not None:
            return self._devices
        if self._registry_source is None and self._load_registries_from_api(result):
            return self._devices or {}
        registry_file = self._storage_dir / "core.device_registry"
        if not registry_file.exists():
            result.errors.append(f"Device registry not found: {registry_file}")
            self._devices = {}
            return self._devices
        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
            self._devices = {
                device["id"]: device
                for device in data.get("data", {}).get("devices", [])
            }
        except Exception as err:
            result.errors.append(f"Failed to load device registry: {err}")
            self._devices = {}
        return self._devices

    def load_area_registry(self, result: ValidationResult) -> dict[str, Any]:
        """Load the area registry from HA storage."""
        if self._areas is not None:
            return self._areas
        if self._registry_source is None and self._load_registries_from_api(result):
            return self._areas or {}
        registry_file = self._storage_dir / "core.area_registry"
        if not registry_file.exists():
            result.warnings.append(f"Area registry not found: {registry_file}")
            self._areas = {}
            return self._areas
        try:
            data = json.loads(registry_file.read_text(encoding="utf-8"))
            self._areas = {
                area["id"]: area for area in data.get("data", {}).get("areas", [])
            }
        except Exception as err:
            result.warnings.append(f"Failed to load area registry: {err}")
            self._areas = {}
        return self._areas

    @staticmethod
    def _is_uuid_format(value: str) -> bool:
        return bool(re.match(r"^[a-f0-9]{32}$", value))

    @staticmethod
    def _is_template(value: str) -> bool:
        return bool(re.search(r"\{\{.*?\}\}", value))

    def _should_skip_entity_validation(self, value: str) -> bool:
        """Decide whether an entity value should skip validation."""
        return (
            value.startswith("!")
            or self._is_uuid_format(value)
            or self._is_template(value)
            or value in self.SPECIAL_KEYWORDS
        )

    def extract_entity_references(self, data: Any) -> set[str]:
        """Extract entity_id references from config data."""
        entities: set[str] = set()
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ["entity_id", "entity_ids", "entities"]:
                    if isinstance(value, str):
                        if not self._should_skip_entity_validation(value):
                            entities.add(value)
                    elif isinstance(value, list):
                        for entity in value:
                            if isinstance(
                                entity, str
                            ) and not self._should_skip_entity_validation(entity):
                                entities.add(entity)
                elif key == "data" and isinstance(value, dict):
                    entities.update(self.extract_entity_references(value))
                elif isinstance(value, str) and any(
                    token in value for token in ["state_attr(", "states(", "is_state("]
                ):
                    entities.update(self.extract_entities_from_template(value))
                else:
                    entities.update(self.extract_entity_references(value))
        elif isinstance(data, list):
            for item in data:
                entities.update(self.extract_entity_references(item))
        return entities

    @staticmethod
    def extract_entities_from_template(template: str) -> set[str]:
        """Extract entity references from Jinja templates."""
        entities: set[str] = set()
        patterns = [
            r"states\('([^']+)'\)",
            r'states\("([^"]+)"\)',
            r"states\.([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)",
            r"is_state\('([^']+)'",
            r'is_state\("([^"]+)"',
            r"state_attr\('([^']+)'",
            r'state_attr\("([^"]+)"',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, template):
                if "." in match and len(match.split(".")) == 2:
                    entities.add(match)
        return entities

    def extract_device_references(self, data: Any) -> set[str]:
        """Extract device_id references from config data."""
        devices: set[str] = set()
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ["device_id", "device_ids"]:
                    if isinstance(value, str):
                        if not value.startswith("!") and not self._is_template(value):
                            devices.add(value)
                    elif isinstance(value, list):
                        for device in value:
                            if (
                                isinstance(device, str)
                                and not device.startswith("!")
                                and not self._is_template(device)
                            ):
                                devices.add(device)
                else:
                    devices.update(self.extract_device_references(value))
        elif isinstance(data, list):
            for item in data:
                devices.update(self.extract_device_references(item))
        return devices

    def extract_area_references(self, data: Any) -> set[str]:
        """Extract area_id references from config data."""
        areas: set[str] = set()
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ["area_id", "area_ids"]:
                    if isinstance(value, str):
                        if not value.startswith("!") and not self._is_template(value):
                            areas.add(value)
                    elif isinstance(value, list):
                        for area in value:
                            if isinstance(area, str) and not area.startswith("!"):
                                areas.add(area)
                else:
                    areas.update(self.extract_area_references(value))
        elif isinstance(data, list):
            for item in data:
                areas.update(self.extract_area_references(item))
        return areas

    def extract_entity_registry_ids(self, data: Any) -> set[str]:
        """Extract entity registry UUID references."""
        registry_ids: set[str] = set()
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "entity_id" and isinstance(value, str):
                    if self._is_uuid_format(value):
                        registry_ids.add(value)
                else:
                    registry_ids.update(self.extract_entity_registry_ids(value))
        elif isinstance(data, list):
            for item in data:
                registry_ids.update(self.extract_entity_registry_ids(item))
        return registry_ids

    def get_entity_registry_id_mapping(
        self, entities: dict[str, Any]
    ) -> dict[str, str]:
        """Build mapping of registry IDs to entity_ids."""
        return {
            entity_data["id"]: entity_data["entity_id"]
            for entity_data in entities.values()
            if "id" in entity_data
        }

    def validate(self, data: Any, result: ValidationResult) -> None:
        """Validate entity, device, and area references."""
        entity_refs = self.extract_entity_references(data)
        device_refs = self.extract_device_references(data)
        area_refs = self.extract_area_references(data)
        registry_ids = self.extract_entity_registry_ids(data)

        entities = self.load_entity_registry(result)
        devices = self.load_device_registry(result)
        areas = self.load_area_registry(result)
        entity_id_mapping = self.get_entity_registry_id_mapping(entities)

        for entity_id in entity_refs:
            if self._is_uuid_format(entity_id):
                continue
            if entity_id not in entities:
                disabled_entities = {
                    e["entity_id"]: e
                    for e in entities.values()
                    if e.get("disabled_by") is not None
                }
                if entity_id in disabled_entities:
                    result.warnings.append(
                        f"{self._label}: References disabled entity '{entity_id}'"
                    )
                else:
                    result.errors.append(f"{self._label}: Unknown entity '{entity_id}'")

        for registry_id in registry_ids:
            if registry_id not in entity_id_mapping:
                result.errors.append(
                    f"{self._label}: Unknown entity registry ID '{registry_id}'"
                )
            else:
                actual_entity_id = entity_id_mapping[registry_id]
                entity_data = entities.get(actual_entity_id)
                if entity_data and entity_data.get("disabled_by") is not None:
                    result.warnings.append(
                        f"{self._label}: Entity registry ID '{registry_id}' "
                        f"references disabled entity '{actual_entity_id}'"
                    )

        for device_id in device_refs:
            if device_id not in devices:
                result.errors.append(f"{self._label}: Unknown device '{device_id}'")

        for area_id in area_refs:
            if area_id not in areas:
                result.warnings.append(f"{self._label}: Unknown area '{area_id}'")


def _validate_automations_structure(
    automations: Any, result: ValidationResult, *, label: str
) -> None:
    if automations is None:
        return
    if not isinstance(automations, list):
        result.errors.append(f"{label}: Automations must be a list")
        return

    for i, automation in enumerate(automations):
        if not isinstance(automation, dict):
            result.errors.append(f"{label}: Automation {i} must be a dictionary")
            continue

        if "use_blueprint" not in automation:
            if "trigger" not in automation and "triggers" not in automation:
                result.errors.append(
                    f"{label}: Automation {i} missing 'trigger' or 'triggers'"
                )
            if "action" not in automation and "actions" not in automation:
                result.errors.append(
                    f"{label}: Automation {i} missing 'action' or 'actions'"
                )

        if "alias" not in automation:
            result.warnings.append(
                f"{label}: Automation {i} missing 'alias' (recommended)"
            )


def validate_automations_yaml(
    hass: HomeAssistant, content: str, *, label: str = "automations.yaml"
) -> ValidationResult:
    """Validate automations YAML content using shared validators."""
    result = ValidationResult()
    try:
        automations = yaml.load(content, Loader=HAYamlLoader)
    except yaml.YAMLError as err:
        raise HomeAssistantError(f"YAML validation error: {err}") from err
    except Exception as err:
        raise HomeAssistantError(f"YAML validation failed: {err}") from err

    _validate_automations_structure(automations, result, label=label)
    EntityReferenceValidator(hass, label=label).validate(automations, result)
    return result
