# Copyright (c) Microsoft. All rights reserved.
from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import sign_in  # noqa: E402


@pytest.mark.parametrize("existing", [False, True])
def test_sign_in_requests_blueprint_scope_and_protects_token_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], existing: bool,
) -> None:
    output = tmp_path / ".user-token"
    if existing:
        output.write_text("old-token")
        output.chmod(0o644)
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    monkeypatch.setenv("AGENT_BLUEPRINT_APP_ID", "new-blueprint")
    monkeypatch.setenv("AGENT_PUBLIC_CLIENT_ID", "public-client")
    monkeypatch.setenv("AGENT_USER_ASSERTION_FILE", str(output))

    class Client:
        def __init__(self, client_id: str, **kwargs: Any) -> None:
            assert client_id == "public-client"
            assert kwargs["authority"].endswith("/tenant")

        def initiate_device_flow(self, scopes: list[str]) -> dict[str, str]:
            assert scopes == ["api://new-blueprint/access_agent"]
            return {"user_code": "code", "message": "Complete sign-in"}

        def acquire_token_by_device_flow(self, flow: Any) -> dict[str, str]:
            return {"access_token": "private-user-assertion"}

    monkeypatch.setattr(sign_in, "PublicClientApplication", Client)
    assert sign_in.main() == 0
    assert output.read_text() == "private-user-assertion"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "private-user-assertion" not in capsys.readouterr().out


def test_failed_sign_in_does_not_create_token_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AZURE_TENANT_ID", "AGENT_BLUEPRINT_APP_ID", "AGENT_PUBLIC_CLIENT_ID"):
        monkeypatch.setenv(name, "configured")
    output = tmp_path / ".user-token"
    monkeypatch.setenv("AGENT_USER_ASSERTION_FILE", str(output))

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def initiate_device_flow(self, scopes: list[str]) -> dict[str, str]:
            return {"error_description": "device code flow is disabled"}

    monkeypatch.setattr(sign_in, "PublicClientApplication", Client)
    with pytest.raises(RuntimeError, match="device code flow is disabled"):
        sign_in.main()
    assert not output.exists()
