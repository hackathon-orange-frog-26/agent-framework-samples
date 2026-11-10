"""Configuration shared by deployment, invocation, and the hosted runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model_deployment: str
    toolbox_name: str = "WorkIQToolbox"
    toolbox_version: str = "1"


def get_settings() -> Settings:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT environment variable is required.")
    toolbox_name = os.environ.get("TOOLBOX_NAME", "WorkIQToolbox").strip()
    toolbox_version = os.environ.get("TOOLBOX_VERSION", "1").strip()
    if toolbox_name and not toolbox_version:
        raise ValueError("TOOLBOX_VERSION is required when TOOLBOX_NAME is set.")
    return Settings(
        project_endpoint=endpoint,
        model_deployment=(
            os.environ.get("FOUNDRY_MODEL_DEPLOYMENT", "").strip()
            or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "").strip()
            or "gpt-5.3-codex-2"
        ),
        toolbox_name=toolbox_name,
        toolbox_version=toolbox_version,
    )
