# Copyright (c) Microsoft. All rights reserved.
"""Provision a sandbox and execute the agent process inside it as an agent identity."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Settings

WORKSPACE = "/workspace"
REMOTE_AGENT = f"{WORKSPACE}/sandbox_agent.py"
REMOTE_REQUIREMENTS = f"{WORKSPACE}/requirements-sandbox.txt"
REMOTE_REQUEST = f"{WORKSPACE}/request.json"


@dataclass(frozen=True)
class AgentRunResult:
    answer: str
    agent_identity: str
    blueprint: str
    user_agent: str


def default_client_factory(settings: Settings) -> Any:
    from azure.containerapps.sandbox import endpoint_for_region
    from azure.containerapps.sandbox.aio import SandboxGroupClient
    from azure.identity.aio import DefaultAzureCredential

    credential = DefaultAzureCredential()
    client = SandboxGroupClient(
        endpoint_for_region(settings.sandbox_region),
        credential,
        subscription_id=settings.subscription_id,
        resource_group=settings.resource_group,
        sandbox_group=settings.sandbox_group,
    )
    return client, credential


class AgentIdentitySandboxAgent:
    """Upload and invoke a trusted agent process that authenticates as an agent identity."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[[Settings], tuple[Any, Any]] = default_client_factory,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory

    async def run(self, question: str) -> AgentRunResult:
        group_client, credential = self._client_factory(self._settings)
        sandbox = None
        try:
            poller = await group_client.begin_create_sandbox(
                disk=self._settings.sandbox_disk_image,
                labels={
                    "sample": "agent365-identity-agent",
                    "agent-identity": self._settings.identity.agent_identity_client_id or "",
                },
            )
            sandbox = await poller.result()
            await sandbox.mkdir(WORKSPACE)
            await self._upload_runtime(sandbox, question)

            install = await sandbox.exec(
                f"python3 -m pip install --disable-pip-version-check -r {REMOTE_REQUIREMENTS}",
                working_directory=WORKSPACE,
            )
            if install.exit_code != 0:
                raise RuntimeError(f"Sandbox dependency installation failed:\n{install.stderr}")

            result = await sandbox.exec(
                f"python3 {REMOTE_AGENT} --request {REMOTE_REQUEST}",
                working_directory=WORKSPACE,
            )
            if result.exit_code != 0:
                raise RuntimeError(f"Sandbox agent failed:\n{result.stderr}")
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            return AgentRunResult(
                answer=payload["answer"],
                agent_identity=payload["agent_identity"],
                blueprint=payload["blueprint"],
                user_agent=payload["user_agent"],
            )
        finally:
            if sandbox is not None:
                try:
                    await sandbox.exec(f"rm -f {REMOTE_REQUEST}")
                finally:
                    await sandbox.delete()
            await group_client.close()
            await credential.close()

    async def _upload_runtime(self, sandbox: Any, question: str) -> None:
        source = Path(__file__).with_name("sandbox_agent.py").read_text(encoding="utf-8")
        requirements = Path(__file__).parents[1].joinpath("requirements-sandbox.txt").read_text(encoding="utf-8")
        request = {
            "tenant_id": self._settings.identity.tenant_id,
            "blueprint_app_id": self._settings.identity.blueprint_app_id,
            "managed_identity_client_id": self._settings.identity.managed_identity_client_id,
            "project_endpoint": self._settings.foundry_project_endpoint,
            "model_deployment": self._settings.foundry_model_deployment,
            "agent_identity_client_id": self._settings.identity.agent_identity_client_id,
            "question": question,
        }
        await sandbox.write_file(REMOTE_AGENT, source)
        await sandbox.write_file(
            f"{WORKSPACE}/agent_token.py", Path(__file__).with_name("agent_token.py").read_text(encoding="utf-8")
        )
        await sandbox.write_file(REMOTE_REQUIREMENTS, requirements)
        await sandbox.write_file(REMOTE_REQUEST, json.dumps(request))
        await sandbox.exec(f"chmod 600 {REMOTE_REQUEST}")
