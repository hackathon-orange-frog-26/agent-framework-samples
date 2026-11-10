"""Bounded ARM operations authenticated only as the hosted agent identity."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated

from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.mgmt.resource.resources.aio import ResourceManagementClient
from azure.mgmt.resource.resources.models import ResourceGroup

from .config import Settings


class AzureResourceGroupTools:
    def __init__(
        self, settings: Settings, credential_factory: Callable[[], AsyncTokenCredential],
    ) -> None:
        settings.validate_azure()
        self.settings = settings
        self.credential_factory = credential_factory

    def _validate_name(self, name: str) -> None:
        if (
            not re.fullmatch(r"[a-zA-Z0-9_-]{1,90}", name)
            or not name.startswith(self.settings.resource_group_prefix)
            or len(name) == len(self.settings.resource_group_prefix)
        ):
            raise ValueError(
                f"Resource group name must start with {self.settings.resource_group_prefix!r}, "
                "include a suffix, and contain at most 90 ASCII letters, digits, '_' or '-'."
            )

    @staticmethod
    def _details(group: ResourceGroup) -> dict:
        return {
            "id": group.id,
            "name": group.name,
            "location": group.location,
            "tags": group.tags,
            "provisioning_state": (
                group.properties.provisioning_state if group.properties else None
            ),
        }

    def azure_deployment_context(self) -> dict:
        """Return the operator-configured Azure deployment boundary, without tokens."""
        return {
            "subscription_id": self.settings.azure_subscription_id,
            "resource_group_prefix": self.settings.resource_group_prefix,
            "location": self.settings.resource_group_location,
            "authentication": "Hosted agent instance identity via ManagedIdentityCredential",
            "operations": ["list_resource_groups", "get_resource_group", "deploy_resource_group"],
        }

    async def list_resource_groups(self) -> list[dict]:
        """List only resource groups matching the configured workshop prefix."""
        async with self.credential_factory() as credential, ResourceManagementClient(
            credential, self.settings.azure_subscription_id,
        ) as client:
            return [
                self._details(group)
                async for group in client.resource_groups.list()
                if group.name and group.name.startswith(self.settings.resource_group_prefix)
            ]

    async def get_resource_group(
        self, name: Annotated[str, "Exact resource group name including the configured prefix"],
    ) -> dict:
        """Read a resource group inside the configured subscription and name boundary."""
        self._validate_name(name)
        async with self.credential_factory() as credential, ResourceManagementClient(
            credential, self.settings.azure_subscription_id,
        ) as client:
            return self._details(await client.resource_groups.get(name))

    async def deploy_resource_group(
        self, name: Annotated[str, "New empty resource group name including the configured prefix"],
    ) -> dict:
        """Create an empty group in the fixed region; return existing groups unchanged."""
        self._validate_name(name)
        async with self.credential_factory() as credential, ResourceManagementClient(
            credential, self.settings.azure_subscription_id,
        ) as client:
            try:
                existing = await client.resource_groups.get(name)
            except ResourceNotFoundError:
                existing = None
            if existing is not None:
                if existing.location != self.settings.resource_group_location:
                    raise ValueError("Existing resource group is in a different region; no changes made.")
                return {"outcome": "existing_unchanged", **self._details(existing)}

            await client.resource_groups.create_or_update(
                name,
                ResourceGroup(
                    location=self.settings.resource_group_location,
                    tags={"sample": "microsoft-enterprise-architect-azure-hosted"},
                ),
            )
            group = await client.resource_groups.get(name)
            if (
                group.location != self.settings.resource_group_location
                or not group.id
                or not group.properties
                or group.properties.provisioning_state != "Succeeded"
            ):
                raise RuntimeError("Resource group write returned, but read-back did not verify success.")
            return {"outcome": "created_and_verified", **self._details(group)}
