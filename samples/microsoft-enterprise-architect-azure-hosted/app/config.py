"""Configuration shared by deployment, invocation, and the hosted runtime."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model_deployment: str
    workiq_connection_name: str = ""
    workiq_connection_id: str = ""
    azure_subscription_id: str = ""
    resource_group_prefix: str = "mea-agent-"
    resource_group_location: str = "eastus"

    def validate_azure(self) -> None:
        try:
            if str(UUID(self.azure_subscription_id)) != self.azure_subscription_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("AZURE_SUBSCRIPTION_ID must be a canonical lowercase UUID.") from exc
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,38}-", self.resource_group_prefix):
            raise ValueError("AZURE_RESOURCE_GROUP_PREFIX must be 2-40 lowercase letters/digits/hyphens, ending in '-'.")
        if not re.fullmatch(r"[a-z][a-z0-9]+", self.resource_group_location):
            raise ValueError("AZURE_RESOURCE_GROUP_LOCATION must be an Azure region name such as eastus.")


def get_settings() -> Settings:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT environment variable is required.")
    return Settings(
        project_endpoint=endpoint,
        model_deployment=(
            os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "").strip()
            or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()
            or "gpt-5.3-codex-2"
        ),
        workiq_connection_name=os.environ.get("WORKIQ_CONNECTION_NAME", "").strip(),
        workiq_connection_id=os.environ.get("WORKIQ_CONNECTION_ID", "").strip(),
        azure_subscription_id=os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip(),
        resource_group_prefix=os.environ.get("AZURE_RESOURCE_GROUP_PREFIX", "mea-agent-").strip(),
        resource_group_location=os.environ.get("AZURE_RESOURCE_GROUP_LOCATION", "eastus").strip(),
    )
