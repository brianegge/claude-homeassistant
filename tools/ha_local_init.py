#!/usr/bin/env python3
"""Initialize a local Home Assistant Core config for dev/testing."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

DEFAULT_CONFIG = """default_config:

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

logger:
  default: info
  logs:
    custom_components.claude_agent: debug
"""

DEFAULT_AUTOMATIONS = "[]\n"
DEFAULT_SCRIPTS = "{}\n"
DEFAULT_SCENES = "{}\n"
DEFAULT_SECRETS = 'example_secret: "change_me"\n'


def _ensure_file(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _ensure_symlink(link_path: Path, target: Path, *, force: bool) -> str:
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_symlink() and link_path.resolve() == target.resolve():
            return "kept"
        if not force:
            return "skipped"
        if link_path.is_dir() and not link_path.is_symlink():
            for child in link_path.iterdir():
                if child.is_dir():
                    _remove_tree(child)
                else:
                    child.unlink()
            link_path.rmdir()
        else:
            link_path.unlink()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target, target.is_dir())
    return "linked"


def _remove_tree(path: Path) -> None:
    """Remove a directory tree without relying on shutil."""
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for local HA config initialization."""
    parser = argparse.ArgumentParser(
        description="Initialize a local Home Assistant config directory."
    )
    parser.add_argument(
        "--config-path",
        default=os.getenv("HA_LOCAL_CONFIG_PATH", "config-local"),
        type=Path,
        help="Local HA config directory.",
    )
    parser.add_argument(
        "--component-path",
        default=Path("custom_components/claude_agent"),
        type=Path,
        help="Path to the Claude Agent integration source.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing custom_components link if needed.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the local HA config initialization workflow."""
    args = parse_args()
    config_path: Path = args.config_path
    component_path: Path = args.component_path

    config_path.mkdir(parents=True, exist_ok=True)
    created = []

    if _ensure_file(config_path / "configuration.yaml", DEFAULT_CONFIG):
        created.append("configuration.yaml")
    if _ensure_file(config_path / "automations.yaml", DEFAULT_AUTOMATIONS):
        created.append("automations.yaml")
    if _ensure_file(config_path / "scripts.yaml", DEFAULT_SCRIPTS):
        created.append("scripts.yaml")
    if _ensure_file(config_path / "scenes.yaml", DEFAULT_SCENES):
        created.append("scenes.yaml")
    if _ensure_file(config_path / "secrets.yaml", DEFAULT_SECRETS):
        created.append("secrets.yaml")

    component_path = component_path.resolve()
    if not component_path.exists():
        print(f"Missing integration path: {component_path}")
        return 1

    link_path = config_path / "custom_components" / "claude_agent"
    link_status = _ensure_symlink(link_path, component_path, force=args.force)

    print(f"Local config: {config_path.resolve()}")
    if created:
        print(f"Created files: {', '.join(created)}")
    else:
        print("Config files already present.")
    print(f"Integration link: {link_status} -> {component_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
