"""Expose the code-owned agent through the Foundry Responses protocol."""

from __future__ import annotations

from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import ManagedIdentityCredential
from azure.identity.aio import ManagedIdentityCredential as AsyncManagedIdentityCredential

from .agent import create_agent
from .config import get_settings


def main() -> None:
    settings = get_settings()
    settings.validate_azure()
    with ManagedIdentityCredential() as credential:
        server = ResponsesHostServer(
            agent=lambda: create_agent(settings, credential, AsyncManagedIdentityCredential)
        )
        server.run()


if __name__ == "__main__":
    main()
