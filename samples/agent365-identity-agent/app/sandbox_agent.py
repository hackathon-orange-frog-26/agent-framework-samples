# Copyright (c) Microsoft. All rights reserved.
"""Agent Framework process executed inside the sandbox as an Entra agent identity."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from microsoft_agents_a365.runtime import Utility


class FileTokenCredential:
    """Serve the short-lived agent identity token supplied by the trusted host launcher."""

    def __init__(self, token_path: Path) -> None:
        from azure.core.credentials import AccessToken

        token = json.loads(token_path.read_text(encoding="utf-8"))
        self.token = token["token"]
        self._access_token = AccessToken(token["token"], token["expires_on"])

    def get_token(self, *scopes: str, **kwargs: Any) -> Any:
        return self._access_token


def describe_identity(token: str, expected_agent_identity: str) -> dict[str, str]:
    """Resolve which Agent 365 identity this process runs as.

    The Agent 365 SDK reads the agent identity (``appid``/``azp``) and the parent blueprint
    (``xms_par_app_azp``) from the token. Signatures are not verified here, so this is a
    diagnostic check that catches misconfiguration, not an authorization decision.
    """
    agent_identity = Utility.get_app_id_from_token(token)
    blueprint = Utility.get_agent_id_from_token(token)
    if agent_identity != expected_agent_identity:
        raise RuntimeError(
            f"Token was issued to {agent_identity or 'an unknown client'}, expected agent identity "
            f"{expected_agent_identity}"
        )
    return {
        "agent_identity": agent_identity,
        "blueprint": blueprint,
        "user_agent": Utility.get_user_agent_header("AgentFramework"),
    }


async def run(request_path: Path, token_path: Path) -> dict[str, Any]:
    """Run one request through an agent that authenticates as its own agent identity."""
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient

    request = json.loads(request_path.read_text(encoding="utf-8"))
    credential = FileTokenCredential(token_path)
    identity = describe_identity(credential.token, request["agent_identity_client_id"])

    client = FoundryChatClient(
        project_endpoint=request["project_endpoint"],
        model=request["model_deployment"],
        credential=credential,
    )
    agent = Agent(
        client=client,
        name="agent365-identity-agent",
        instructions="Answer the user's question directly and concisely.",
    )
    response = await agent.run(request["question"])
    return {**identity, "answer": str(response)}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--token", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(await run(args.request, args.token)))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
