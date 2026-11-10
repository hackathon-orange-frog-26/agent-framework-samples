"""Configuration shared by deployment, invocation, and the hosted runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model_deployment: str
    workiq_connection_id: str = ""
    sharepoint_connection_id: str = ""
    sharepoint_server_url: str = ""


def validate_sharepoint_url(url: str) -> str:
    url = url.rstrip("/")
    prefix = "https://agent365.svc.cloud.microsoft/agents/tenants/"
    suffix = "/servers/mcp_SharePointRemoteServer"
    tenantless = f"https://agent365.svc.cloud.microsoft/agents{suffix}"
    if url == tenantless:
        return url
    if not (url.startswith(prefix) and url.endswith(suffix)):
        raise ValueError(
            f"SharePoint connection must target {tenantless} or {prefix}<tenant-id>{suffix}."
        )
    try:
        UUID(url[len(prefix):-len(suffix)])
    except ValueError as exc:
        raise ValueError("SharePoint connection must contain a valid tenant UUID.") from exc
    return url


def get_settings() -> Settings:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT environment variable is required.")
    connection_id = os.environ.get("SHAREPOINT_CONNECTION_ID", "").strip()
    server_url = os.environ.get("SHAREPOINT_SERVER_URL", "").strip()
    if bool(connection_id) != bool(server_url):
        raise ValueError("SharePoint requires both a connection ID and server URL.")
    return Settings(
        project_endpoint=endpoint,
        model_deployment=(
            os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "").strip()
            or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()
            or "gpt-5.3-codex-2"
        ),
        workiq_connection_id=os.environ.get("WORKIQ_CONNECTION_ID", "").strip(),
        sharepoint_connection_id=connection_id,
        sharepoint_server_url=validate_sharepoint_url(server_url) if server_url else "",
    )
