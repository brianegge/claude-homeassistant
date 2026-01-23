#!/usr/bin/env python3
"""End-to-end validation for the Claude Agent local HA flow."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any
from urllib.parse import urlparse

import aiohttp

DEFAULT_URL = "http://localhost:8123"
DEFAULT_PROMPT = (
    "Add a new automation with id 'codex_e2e_local_test' and alias "
    "'Codex E2E Local Test'. Trigger at 00:00 daily. Action: logbook.log "
    "with message 'Codex E2E test'. Return the full updated automations.yaml."
)


class WSClient:
    """Simple Home Assistant WebSocket client wrapper."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Store websocket and initialize message id counter."""
        self._ws = ws
        self._next_id = 1

    async def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a WS request and return its result payload."""
        msg_id = self._next_id
        self._next_id += 1
        payload = {**payload, "id": msg_id}
        await self._ws.send_json(payload)

        while True:
            message = await self._ws.receive()
            if message.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(message.data)
                if data.get("id") != msg_id:
                    continue
                if data.get("type") == "result":
                    if not data.get("success", True):
                        error = data.get("error", {})
                        raise RuntimeError(
                            f"WS error {error.get('code')}: {error.get('message')}"
                        )
                    return data.get("result") or {}
                if data.get("type") == "error":
                    error = data.get("error", {})
                    raise RuntimeError(
                        f"WS error {error.get('code')}: {error.get('message')}"
                    )
            elif message.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError(f"WebSocket error: {self._ws.exception()}")
            elif message.type == aiohttp.WSMsgType.CLOSED:
                raise RuntimeError("WebSocket closed unexpectedly.")

    async def close(self) -> None:
        """Close the websocket."""
        await self._ws.close()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the E2E run."""
    parser = argparse.ArgumentParser(
        description="Validate the Claude Agent local HA flow end to end."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("HA_LOCAL_URL", DEFAULT_URL),
        help="Home Assistant base URL (default: http://localhost:8123).",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("HA_LOCAL_TOKEN", ""),
        help="Long-lived access token for localhost.",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt sent to the Claude Agent chat endpoint.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Seconds to wait for HA API availability.",
    )
    parser.add_argument(
        "--keep-changes",
        action="store_true",
        help="Keep the generated automations instead of restoring.",
    )
    return parser.parse_args()


def _require_token(token: str) -> str:
    if token:
        return token
    raise RuntimeError(
        "Missing HA token. Set HA_LOCAL_TOKEN or pass --token for localhost."
    )


def _build_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/api/websocket"


async def _wait_for_api(
    session: aiohttp.ClientSession,
    base_url: str,
    headers: dict[str, str],
    timeout: int,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            async with session.get(f"{base_url}/api/", headers=headers) as response:
                if response.status == 200:
                    return
                last_error = RuntimeError(f"API status {response.status}")
        except Exception as err:  # pragma: no cover - network timing variance
            last_error = err
        await asyncio.sleep(1)

    raise RuntimeError(f"Home Assistant API not ready: {last_error}")


async def _api_request(
    session: aiohttp.ClientSession,
    method: str,
    base_url: str,
    headers: dict[str, str],
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{base_url}{path}"
    async with session.request(method, url, json=payload, headers=headers) as response:
        body = await response.text()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"{method} {path} failed: {response.status} {body}")
        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{method} {path} returned invalid JSON: {body}"
            ) from exc


async def _connect_ws(
    session: aiohttp.ClientSession, base_url: str, token: str
) -> WSClient:
    ws = await session.ws_connect(_ws_url(base_url))
    auth_required = await ws.receive_json()
    if auth_required.get("type") != "auth_required":
        await ws.close()
        raise RuntimeError("WebSocket did not request auth.")
    await ws.send_json({"type": "auth", "access_token": token})
    auth_ok = await ws.receive_json()
    if auth_ok.get("type") != "auth_ok":
        await ws.close()
        raise RuntimeError(f"WebSocket auth failed: {auth_ok}")
    return WSClient(ws)


async def run() -> int:
    """Run the end-to-end validation flow."""
    args = parse_args()
    token = _require_token(args.token)
    base_url = args.url.rstrip("/")
    headers = _build_headers(token)

    async with aiohttp.ClientSession() as session:
        await _wait_for_api(session, base_url, headers, args.timeout)

        status = await _api_request(
            session, "GET", base_url, headers, "/api/claude_agent/status"
        )
        cli = status.get("cli", {})
        if not cli.get("available"):
            raise RuntimeError(
                f"Claude CLI not available: {cli.get('error') or 'unknown error'}"
            )

        ws_client = await _connect_ws(session, base_url, token)
        original = ""
        updated_yaml = ""
        wrote_update = False
        try:
            info = await ws_client.call({"type": "claude_agent/get_info"})
            if not info.get("automations_path"):
                raise RuntimeError(
                    "WebSocket get_info did not return automations_path."
                )
            automations = await ws_client.call({"type": "claude_agent/get_automations"})
            original = automations.get("content", "")

            chat = await _api_request(
                session,
                "POST",
                base_url,
                headers,
                "/api/claude_agent/chat",
                {"prompt": args.prompt},
            )
            updated_yaml = chat.get("updated_yaml") or ""
            if not updated_yaml.strip():
                raise RuntimeError(
                    "Chat response did not return updated_yaml. "
                    "Check integration config and Claude CLI availability."
                )

            warnings = chat.get("warnings") or []
            if warnings:
                print("Warnings:\n- " + "\n- ".join(warnings))

            after_chat = await ws_client.call({"type": "claude_agent/get_automations"})
            if after_chat.get("content", "") != original:
                raise RuntimeError(
                    "automations.yaml changed without explicit save "
                    "(expected unchanged)."
                )

            await ws_client.call(
                {"type": "claude_agent/write_automations", "content": updated_yaml}
            )
            wrote_update = True
            after_write = await ws_client.call({"type": "claude_agent/get_automations"})
            if after_write.get("content", "") != updated_yaml:
                raise RuntimeError(
                    "Saved automations.yaml does not match updated_yaml."
                )
        finally:
            if wrote_update and not args.keep_changes:
                try:
                    await ws_client.call(
                        {"type": "claude_agent/write_automations", "content": original}
                    )
                except Exception as err:
                    print(
                        f"WARNING: failed to restore original automations.yaml: {err}",
                        file=sys.stderr,
                    )
            await ws_client.close()

    print(
        "OK: chat generated draft, file unchanged before explicit save, "
        "save succeeded, and original content restored."
    )
    return 0


def main() -> int:
    """CLI entrypoint for the E2E script."""
    try:
        return asyncio.run(run())
    except Exception as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
