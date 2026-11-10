"""Validate connections, upload Python source, and route a Foundry hosted agent."""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    AgentEndpointProtocol,
    CodeConfiguration,
    CodeDependencyResolution,
    FixedRatioVersionSelectionRule,
    HostedAgentDefinition,
    ProtocolConfiguration,
    ProtocolVersionRecord,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential

from .agent import AGENT_NAME, WORKIQ_MCP_URL
from .config import Settings, get_settings, validate_sharepoint_url


def resolve_connections(
    project: AIProjectClient,
    settings: Settings,
    *,
    workiq_name: str,
    sharepoint_name: str,
) -> Settings:
    workiq_id = ""
    sharepoint_id = ""
    sharepoint_url = ""
    if workiq_name:
        connection = project.connections.get(workiq_name)
        if connection.target.rstrip("/") != WORKIQ_MCP_URL:
            raise ValueError(f"Work IQ connection must target {WORKIQ_MCP_URL}.")
        workiq_id = connection.id
        if not workiq_id:
            raise ValueError("Work IQ connection has no resource ID.")
    if sharepoint_name:
        connection = project.connections.get(sharepoint_name)
        sharepoint_url = validate_sharepoint_url(connection.target)
        sharepoint_id = connection.id
        if not sharepoint_id:
            raise ValueError("SharePoint connection has no resource ID.")
    return replace(
        settings,
        workiq_connection_id=workiq_id,
        sharepoint_connection_id=sharepoint_id,
        sharepoint_server_url=sharepoint_url,
    )


def create_code_zip(source_dir: Path, zip_path: Path) -> None:
    # Only runtime code is uploaded; never include .env, tokens, or dev artifacts.
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for name in (
            "main.py", "requirements.txt", "app/__init__.py",
            "app/agent.py", "app/config.py", "app/host.py",
        ):
            archive.write(source_dir / name, name)


def wait_until_active(
    project: AIProjectClient, agent_name: str, version: str, *, timeout: float = 600,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = project.agents.get_version(agent_name=agent_name, agent_version=version)
        status = info["status"]
        print(f"Version {version}: {status}", flush=True)
        if status == "active":
            return
        if status in {"failed", "deleting", "deleted"}:
            raise RuntimeError(f"Hosted agent provisioning stopped: {info}")
        time.sleep(5)
    raise TimeoutError(f"Version {version} did not become active within {timeout} seconds.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=AGENT_NAME)
    parser.add_argument("--without-workiq", action="store_true")
    parser.add_argument("--without-sharepoint", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    workiq_name = os.environ.get("WORKIQ_CONNECTION_NAME", "").strip()
    sharepoint_name = os.environ.get("SHAREPOINT_CONNECTION_NAME", "").strip()
    if not args.without_workiq and not workiq_name:
        parser.error("Set WORKIQ_CONNECTION_NAME or explicitly use --without-workiq.")
    if not args.without_sharepoint and not sharepoint_name:
        parser.error("Set SHAREPOINT_CONNECTION_NAME or explicitly use --without-sharepoint.")

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential
    ) as project, tempfile.TemporaryDirectory(prefix="mea-hosted-") as temp_dir:
        runtime = resolve_connections(
            project, settings,
            workiq_name="" if args.without_workiq else workiq_name,
            sharepoint_name="" if args.without_sharepoint else sharepoint_name,
        )
        zip_path = Path(temp_dir) / "agent.zip"
        create_code_zip(Path(__file__).resolve().parent.parent, zip_path)
        with zip_path.open("rb") as code:
            agent = project.agents.create_version_from_code(
                agent_name=args.name,
                definition=HostedAgentDefinition(
                    protocol_versions=[
                        ProtocolVersionRecord(protocol=AgentEndpointProtocol.RESPONSES, version="2.0.0")
                    ],
                    cpu="1",
                    memory="2Gi",
                    code_configuration=CodeConfiguration(
                        runtime="python_3_14",
                        entry_point=["python", "main.py"],
                        dependency_resolution=CodeDependencyResolution.REMOTE_BUILD,
                    ),
                    environment_variables={
                        "FOUNDRY_PROJECT_ENDPOINT": runtime.project_endpoint,
                        "AZURE_AI_MODEL_DEPLOYMENT_NAME": runtime.model_deployment,
                        "WORKIQ_CONNECTION_ID": runtime.workiq_connection_id,
                        "SHAREPOINT_CONNECTION_ID": runtime.sharepoint_connection_id,
                        "SHAREPOINT_SERVER_URL": runtime.sharepoint_server_url,
                    },
                ),
                code=code,
            )
        print(f"Created {agent.name}, version {agent.version}", flush=True)
        wait_until_active(project, args.name, agent.version)
        endpoint = project.agents.get(agent_name=args.name).agent_endpoint
        protocols = endpoint.protocol_configuration if endpoint else None
        protocols = protocols or ProtocolConfiguration()
        protocols.responses = ResponsesProtocolConfiguration()
        project.agents.update_details(
            agent_name=args.name,
            agent_endpoint=AgentEndpointConfig(
                version_selector=VersionSelector(version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version=agent.version, traffic_percentage=100)
                ]),
                protocol_configuration=protocols,
                authorization_schemes=endpoint.authorization_schemes if endpoint else None,
            ),
        )
        print(f"Agent endpoint routed to version {agent.version}", flush=True)
        print(f"Work IQ: {'read-only' if runtime.workiq_connection_id else 'disabled'}")
        print(
            "SharePoint: "
            + ("reads; approval-gated creation" if runtime.sharepoint_connection_id else "disabled")
        )


if __name__ == "__main__":
    main()
