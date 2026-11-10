"""Print the hosted agent instance principal ID for an administrator's RBAC grant."""

from __future__ import annotations

import argparse

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from .agent import AGENT_NAME
from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=AGENT_NAME)
    args = parser.parse_args()
    settings = get_settings()
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential,
    ) as project:
        identity = project.agents.get(agent_name=args.name).instance_identity
        if not identity or not identity.principal_id:
            raise RuntimeError("The hosted agent instance identity is not provisioned yet.")
        print(identity.principal_id)


if __name__ == "__main__":
    main()
