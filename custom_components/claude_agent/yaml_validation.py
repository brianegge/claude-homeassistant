"""YAML validation helpers for Home Assistant configs."""

from __future__ import annotations

import yaml
from homeassistant.exceptions import HomeAssistantError


class HAYamlLoader(yaml.SafeLoader):
    """Custom YAML loader that handles Home Assistant specific tags."""


def _include_constructor(loader, node):
    filename = loader.construct_scalar(node)
    return f"!include {filename}"


def _include_dir_named_constructor(loader, node):
    dirname = loader.construct_scalar(node)
    return f"!include_dir_named {dirname}"


def _include_dir_merge_named_constructor(loader, node):
    dirname = loader.construct_scalar(node)
    return f"!include_dir_merge_named {dirname}"


def _include_dir_merge_list_constructor(loader, node):
    dirname = loader.construct_scalar(node)
    return f"!include_dir_merge_list {dirname}"


def _include_dir_list_constructor(loader, node):
    dirname = loader.construct_scalar(node)
    return f"!include_dir_list {dirname}"


def _input_constructor(loader, node):
    input_name = loader.construct_scalar(node)
    return f"!input {input_name}"


def _secret_constructor(loader, node):
    secret_name = loader.construct_scalar(node)
    return f"!secret {secret_name}"


HAYamlLoader.add_constructor("!include", _include_constructor)
HAYamlLoader.add_constructor("!include_dir_named", _include_dir_named_constructor)
HAYamlLoader.add_constructor(
    "!include_dir_merge_named", _include_dir_merge_named_constructor
)
HAYamlLoader.add_constructor(
    "!include_dir_merge_list", _include_dir_merge_list_constructor
)
HAYamlLoader.add_constructor("!include_dir_list", _include_dir_list_constructor)
HAYamlLoader.add_constructor("!input", _input_constructor)
HAYamlLoader.add_constructor("!secret", _secret_constructor)


def validate_yaml(content: str) -> None:
    """Validate YAML content using HA-aware tags."""
    try:
        yaml.load(content, Loader=HAYamlLoader)
    except yaml.YAMLError as err:
        raise HomeAssistantError(f"YAML validation error: {err}") from err
    except Exception as err:  # pragma: no cover - defensive
        raise HomeAssistantError(f"YAML validation failed: {err}") from err
