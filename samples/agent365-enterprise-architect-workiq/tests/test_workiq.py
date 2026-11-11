# Copyright (c) Microsoft. All rights reserved.
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from azure.core.credentials import AccessToken

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import workiq  # noqa: E402


@pytest.mark.parametrize("enable_actions", [False, True])
def test_unified_endpoint_exposes_full_catalog_without_per_call_approvals(enable_actions: bool) -> None:
    tools, clients = workiq.create_tools(AsyncMock(), enable_actions=enable_actions)
    assert len(tools) == len(clients) == 1
    assert tools[0].name == "WorkIQ"
    assert tools[0].url == "https://workiq.svc.cloud.microsoft/mcp"
    assert tools[0].allowed_tools is None
    assert tools[0].approval_mode == "never_require"
    assert not clients[0].follow_redirects
    asyncio.run(clients[0].aclose())


@pytest.mark.parametrize("enable_actions", [False, True])
def test_real_mcp_discovers_live_catalog_and_uses_workiq_obo_scopes(
    monkeypatch: pytest.MonkeyPatch, enable_actions: bool,
) -> None:
    scopes = (workiq.WORKIQ_ASK_SCOPE, workiq.WORKIQ_ACT_SCOPE) if enable_actions else (workiq.WORKIQ_ASK_SCOPE,)
    credential = AsyncMock()
    credential.get_token.return_value = AccessToken("delegated-workiq-token", 2_000_000_000)
    methods: list[str] = []
    tool_names = ["fetch", "get_schema", "future_generic_tool"]

    async def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://workiq.svc.cloud.microsoft/mcp"
        assert request.headers["Authorization"] == "Bearer delegated-workiq-token"
        if request.method != "POST":
            return httpx.Response(405)
        payload = json.loads(request.content)
        method = payload["method"]
        methods.append(method)
        if method == "server/discover":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": payload["id"],
                "error": {"code": -32601, "message": "Method not found"},
            })
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "ping":
            result = {}
        elif method == "initialize":
            result = {
                "protocolVersion": payload["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "unified-workiq", "version": "1.0"},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": name, "description": name,
                "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
            } for name in tool_names]}
        elif method == "tools/call":
            assert payload["params"]["name"] == "fetch"
            assert payload["params"]["arguments"] == {"path": "/me/messages"}
            result = {"content": [{"type": "text", "text": "Work IQ answer"}]}
        else:
            raise AssertionError(f"Unexpected MCP method: {method}")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        workiq.httpx, "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )

    async def exercise() -> None:
        tools, clients = workiq.create_tools(credential, enable_actions=enable_actions)
        try:
            async with tools[0]:
                assert [function.name for function in tools[0].functions] == tool_names
                result = await tools[0].call_tool("fetch", path="/me/messages")
                assert isinstance(result, list)
                assert [content.text for content in result] == ["Work IQ answer"]
        finally:
            for client in clients:
                await client.aclose()
        assert all(client.is_closed for client in clients)

    asyncio.run(asyncio.wait_for(exercise(), timeout=10))
    assert [method for method in methods if method not in {"server/discover", "ping"}] == [
        "initialize", "notifications/initialized", "tools/list", "tools/call"
    ]
    assert credential.get_token.await_count >= 4
    assert all(call.args == scopes for call in credential.get_token.await_args_list)


def test_obo_consent_errors_propagate_before_sending_mcp_request() -> None:
    credential = AsyncMock()
    credential.get_token.side_effect = RuntimeError("Work IQ consent required")

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError("MCP must not be called without a delegated token")

    async def exercise() -> None:
        async with httpx.AsyncClient(
            auth=workiq.DelegatedMcpAuth(credential, (workiq.WORKIQ_ASK_SCOPE,)),
            transport=httpx.MockTransport(unexpected_request),
        ) as client:
            await client.post(workiq.WORKIQ_MCP_URL)

    with pytest.raises(RuntimeError, match="Work IQ consent required"):
        asyncio.run(exercise())
