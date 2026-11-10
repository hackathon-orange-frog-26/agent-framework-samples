"""Create a workshop agent using existing MCP connections."""

from __future__ import annotations

import argparse
from uuid import UUID

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from .agent import (
    AGENT_NAME,
    DISPLAY_NAME,
    WORKIQ_MCP_URL,
    SHAREPOINT_SERVER_ID,
    create_definition,
)
from .config import get_settings

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=AGENT_NAME)
    parser.add_argument(
        "--without-workiq",
        action="store_true",
        help="Omit Work IQ mail, calendar and Teams access; keep SharePoint.",
    )
    parser.add_argument(
        "--without-sharepoint",
        action="store_true",
        help="Omit the separate SharePoint MCP server.",
    )
    args = parser.parse_args()
    settings = get_settings()
    if not args.without_workiq and not settings.workiq_connection_name:
        parser.error("Set WORKIQ_CONNECTION_NAME or explicitly use --without-workiq.")
    if not args.without_sharepoint and not settings.sharepoint_connection_name:
        parser.error("Set SHAREPOINT_CONNECTION_NAME or explicitly use --without-sharepoint.")

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential
    ) as project:
        connection_id = None
        if not args.without_workiq:
            connection = project.connections.get(settings.workiq_connection_name)
            if connection.target.rstrip("/") != WORKIQ_MCP_URL:
                raise RuntimeError(
                    f"Work IQ connection must target {WORKIQ_MCP_URL}; "
                    "do not reuse a preview A2A or unrelated connection."
                )
            connection_id = connection.id

        sharepoint_connection_id = None
        sharepoint_server_url = None
        if not args.without_sharepoint:
            connection = project.connections.get(settings.sharepoint_connection_name)
            sharepoint_server_url = connection.target.rstrip("/")
            prefix = "https://agent365.svc.cloud.microsoft/agents/tenants/"
            suffix = f"/servers/{SHAREPOINT_SERVER_ID}"
            tenantless_url = f"https://agent365.svc.cloud.microsoft/agents{suffix}"
            if sharepoint_server_url != tenantless_url:
                if not (
                    sharepoint_server_url.startswith(prefix)
                    and sharepoint_server_url.endswith(suffix)
                ):
                    raise RuntimeError(
                        f"SharePoint connection must target {tenantless_url} "
                        f"or {prefix}<tenant-id>{suffix}."
                    )
                tenant_id = sharepoint_server_url[len(prefix):-len(suffix)]
                try:
                    UUID(tenant_id)
                except ValueError as exc:
                    raise RuntimeError("SharePoint connection must contain a valid tenant UUID.") from exc
            sharepoint_connection_id = connection.id

        agent = project.agents.create_version(
            agent_name=args.name,
            definition=create_definition(
                settings,
                workiq_connection_id=connection_id,
                sharepoint_connection_id=sharepoint_connection_id,
                sharepoint_server_url=sharepoint_server_url,
            ),
            description=(
                f"{DISPLAY_NAME}: architecture safety workshop"
                + (" with auto-approved WorkIQ reads." if connection_id else " without WorkIQ.")
                + (" With SharePoint reads and approval-gated creation." if sharepoint_connection_id else " Without SharePoint.")
            ),
        )

        print(f"Created {agent.name}, version {agent.version}")
        mode = (
            "disabled (no mail, calendar or Teams access)" if args.without_workiq
            else "read-only mail, calendar and Teams; auto-approved"
        )
        print(f"Work IQ: {mode}")
        print(
            "SharePoint: "
            + ("reads auto-approved; approval required for file creation" if sharepoint_connection_id else "disabled")
        )
        print("Keep the agent version for app.delete; do not delete shared connections.")


if __name__ == "__main__":
    main()
