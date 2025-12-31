#!/usr/bin/env python3
"""Claude Agent cloud API smoke test.

Calls Anthropic's Messages API with the same prompt shape as the integration
and validates that the response is valid YAML (and detects Markdown fences).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

DEFAULT_MODEL = "claude-3-7-sonnet-20250219"
DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024
TOOL_NAME = "update_automations"
UPDATE_AUTOMATIONS_TOOL = {
    "name": TOOL_NAME,
    "description": "Return the full updated automations.yaml content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "updated_yaml": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["updated_yaml"],
    },
}


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


def load_env_file() -> None:
    """Load environment variables from .env file."""
    env_file = Path(".env")
    if not env_file.exists():
        return
    with env_file.open() as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def validate_yaml_content(content: str) -> tuple[bool, str | None]:
    """Validate YAML content using HA-aware tags."""
    try:
        yaml.load(content, Loader=HAYamlLoader)
    except yaml.YAMLError as err:
        return False, f"YAML validation error: {err}"
    except Exception as err:
        return False, f"YAML validation failed: {err}"
    return True, None


def extract_text(data: dict[str, Any]) -> str:
    """Extract concatenated text blocks from Anthropic response JSON."""
    content = data.get("content", [])
    if isinstance(content, str):
        return content
    texts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
    return "".join(texts)


FENCE_RE = re.compile(r"```(?:yaml)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def extract_fenced_yaml(content: str) -> str | None:
    """Extract the first fenced code block (if present)."""
    match = FENCE_RE.search(content)
    if not match:
        return None
    return match.group(1).strip("\n")


def extract_tool_input(data: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    """Extract the first tool input payload for a named tool."""
    content = data.get("content", [])
    if not isinstance(content, list):
        return None
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") == tool_name
        ):
            input_data = block.get("input")
            return input_data if isinstance(input_data, dict) else None
    return None


def build_user_prompt(current_yaml: str, task: str, *, fence_yaml: bool) -> str:
    """Build the user prompt with optional fenced YAML context."""
    if fence_yaml:
        current = f"```yaml\n{current_yaml}\n```"
    else:
        current = current_yaml
    return f"Current YAML:\n{current}\n\nTask:\n{task}\n"


def call_anthropic(
    *,
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None,
    timeout: int,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the Anthropic Messages API and return the decoded JSON response."""
    url = f"{base_url.rstrip('/')}/v1/messages"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if system_prompt:
        payload["system"] = system_prompt
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the smoke test runner."""
    max_tokens_env = os.getenv("ANTHROPIC_MAX_TOKENS")
    if max_tokens_env:
        try:
            max_tokens_default = int(max_tokens_env)
        except ValueError:
            max_tokens_default = DEFAULT_MAX_TOKENS
    else:
        max_tokens_default = DEFAULT_MAX_TOKENS

    parser = argparse.ArgumentParser(
        description="Run Claude Agent cloud API smoke tests."
    )
    parser.add_argument("--prompt", help="Task prompt for the model.")
    parser.add_argument(
        "--prompt-file", type=Path, help="Path to a file containing the prompt."
    )
    parser.add_argument(
        "--current-yaml",
        type=Path,
        default=Path("config/automations.yaml"),
        help="Path to current YAML file.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations to run.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between iterations.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL),
        help="Anthropic model name.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL),
        help="Anthropic base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("ANTHROPIC_API_KEY", ""),
        help="Anthropic API key (or set ANTHROPIC_API_KEY).",
    )
    parser.add_argument(
        "--system-prompt",
        default=(
            "Use the update_automations tool to return the full updated YAML. "
            "Preserve structure and do not include Markdown fences."
        ),
        help="System prompt for the model.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=max_tokens_default,
        help="Max tokens for the response.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--no-fence-current",
        action="store_true",
        help="Do not wrap current YAML in a fenced code block.",
    )
    parser.add_argument(
        "--no-tool",
        action="store_true",
        help="Disable tool-calling and validate raw text response.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Optional directory to write responses for inspection.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the smoke tests and print validation results."""
    load_env_file()
    args = parse_args()
    use_tool = not args.no_tool

    prompt = args.prompt
    if not prompt and args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        print("Error: Provide --prompt or --prompt-file.", file=sys.stderr)
        return 2

    if not args.api_key:
        print(
            "Error: Missing Anthropic API key. Set ANTHROPIC_API_KEY or --api-key.",
            file=sys.stderr,
        )
        return 2

    if not args.current_yaml.exists():
        print(
            f"Error: Current YAML file not found: {args.current_yaml}",
            file=sys.stderr,
        )
        return 2

    current_yaml = args.current_yaml.read_text(encoding="utf-8")
    out_dir = args.out_dir
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for iteration in range(1, args.iterations + 1):
        user_prompt = build_user_prompt(
            current_yaml, prompt, fence_yaml=not args.no_fence_current
        )
        print(
            f"Iteration {iteration}/{args.iterations}: "
            f"model={args.model} base_url={args.base_url}"
        )
        try:
            data = call_anthropic(
                api_key=args.api_key,
                base_url=args.base_url,
                model=args.model,
                system_prompt=args.system_prompt,
                user_prompt=user_prompt,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
                tools=[UPDATE_AUTOMATIONS_TOOL] if use_tool else None,
                tool_choice={"type": "tool", "name": TOOL_NAME} if use_tool else None,
            )
        except requests.HTTPError as err:
            response = err.response
            body = response.text if response is not None else str(err)
            print(f"  HTTP error: {err} body={body[:500]}")
            return 1
        except Exception as err:
            print(f"  Request failed: {err}")
            return 1

        response_text = extract_text(data)
        tool_input = extract_tool_input(data, TOOL_NAME) if use_tool else None
        updated_yaml = None
        summary = ""
        if use_tool:
            if not tool_input or "updated_yaml" not in tool_input:
                print("  Error: missing tool output updated_yaml.")
                return 1
            updated_yaml = tool_input["updated_yaml"]
            if not isinstance(updated_yaml, str):
                print("  Error: tool updated_yaml is not a string.")
                return 1
            summary = (
                tool_input.get("summary", "") if isinstance(tool_input, dict) else ""
            )
            content_to_validate = updated_yaml
        else:
            content_to_validate = response_text

        has_fence = "```" in content_to_validate
        raw_ok, raw_err = validate_yaml_content(content_to_validate)
        fenced_yaml = None
        fenced_ok = False
        fenced_err = None
        if not use_tool and not raw_ok:
            fenced_yaml = extract_fenced_yaml(response_text)
            if fenced_yaml:
                fenced_ok, fenced_err = validate_yaml_content(fenced_yaml)

        usage = data.get("usage", {})
        if isinstance(usage, dict) and usage:
            usage_summary = json.dumps(usage, sort_keys=True)
        else:
            usage_summary = "n/a"

        print(
            f"  Response chars={len(response_text)} tool={use_tool} "
            f"fence={has_fence} yaml_ok={raw_ok} usage={usage_summary}"
        )
        if use_tool and summary:
            print(f"  Tool summary: {summary}")
        if raw_err:
            print(f"  YAML error: {raw_err}")
        if fenced_yaml:
            print(f"  Fenced YAML valid={fenced_ok}")
            if fenced_err:
                print(f"  Fenced YAML error: {fenced_err}")

        if out_dir:
            suffix = f"{int(time.time())}_{iteration}"
            (out_dir / f"response_{suffix}.txt").write_text(
                response_text, encoding="utf-8"
            )
            if updated_yaml is not None:
                (out_dir / f"response_{suffix}.yaml").write_text(
                    updated_yaml, encoding="utf-8"
                )
            elif fenced_yaml:
                (out_dir / f"response_{suffix}.yaml").write_text(
                    fenced_yaml, encoding="utf-8"
                )

        if iteration < args.iterations and args.sleep:
            time.sleep(args.sleep)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
