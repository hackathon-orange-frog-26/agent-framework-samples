# Copyright (c) Microsoft. All rights reserved.
"""Connect to the unified Work IQ MCP endpoint with delegated agent-identity OBO."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
from agent_framework import MCPStreamableHTTPTool
from azure.core.credentials_async import AsyncTokenCredential
from microsoft_agents_a365.runtime import Utility

WORKIQ_MCP_URL = "https://workiq.svc.cloud.microsoft/mcp"
WORKIQ_ASK_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"
WORKIQ_ACT_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQ.Act"


class DelegatedMcpAuth(httpx.Auth):
    """Keep MCP requests authenticated with a cached/refreshed Work IQ OBO token."""

    def __init__(self, credential: AsyncTokenCredential, scopes: tuple[str, ...]) -> None:
        self._credential = credential
        self._scopes = scopes

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._credential.get_token(*self._scopes)
        request.headers["Authorization"] = f"Bearer {token.token}"
        yield request


def create_tools(
    credential: AsyncTokenCredential, *, enable_actions: bool = False,
) -> tuple[list[MCPStreamableHTTPTool], list[httpx.AsyncClient]]:
    scopes = (WORKIQ_ASK_SCOPE, WORKIQ_ACT_SCOPE) if enable_actions else (WORKIQ_ASK_SCOPE,)
    client = httpx.AsyncClient(
        auth=DelegatedMcpAuth(credential, scopes),
        headers={"User-Agent": Utility.get_user_agent_header("AgentFramework")},
        follow_redirects=False,
        timeout=90,
    )
    tool = MCPStreamableHTTPTool(
        name="WorkIQ",
        url=WORKIQ_MCP_URL,
        http_client=client,
        load_prompts=False,
        approval_mode="never_require",
    )
    return [tool], [client]
