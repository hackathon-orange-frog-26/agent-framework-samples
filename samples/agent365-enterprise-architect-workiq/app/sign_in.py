# Copyright (c) Microsoft. All rights reserved.
"""Acquire a blueprint-audience user assertion without printing the access token."""

from __future__ import annotations

import os
from pathlib import Path

from msal import PublicClientApplication

from .config import _require


def main() -> int:
    tenant = _require("AZURE_TENANT_ID")
    blueprint = _require("AGENT_BLUEPRINT_APP_ID")
    client = PublicClientApplication(
        _require("AGENT_PUBLIC_CLIENT_ID"),
        authority=f"https://login.microsoftonline.com/{tenant}",
    )
    flow = client.initiate_device_flow(scopes=[f"api://{blueprint}/access_agent"])
    if "user_code" not in flow:
        raise RuntimeError(f"Device sign-in failed: {flow.get('error_description', flow.get('error'))}")
    print(flow["message"], flush=True)
    result = client.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"User sign-in failed: {result.get('error_description', result.get('error'))}")
    path = Path(_require("AGENT_USER_ASSERTION_FILE"))
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(result["access_token"])
    print(f"User assertion saved to {path}. Run this command again when it expires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
