"""Upload shared fictional guidelines and create a separate workshop agent."""

from __future__ import annotations

import argparse
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from .agent import (
    AGENT_NAME,
    DISPLAY_NAME,
    VECTOR_STORE_NAME,
    WORKIQ_MCP_URL,
    create_definition,
)
from .config import get_settings

# Reuse the curated policy corpus, but never the original agent's resources.
GUIDELINES_DIR = (
    Path(__file__).resolve().parents[2]
    / "enterprise-architect-prompt-agent"
    / "internal-guidelines"
)


def guideline_paths() -> list[Path]:
    paths = sorted(GUIDELINES_DIR.glob("*.md"))
    if not paths:
        raise RuntimeError(f"No Markdown guidelines found in {GUIDELINES_DIR}.")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=AGENT_NAME)
    parser.add_argument(
        "--without-workiq",
        action="store_true",
        help="Create a public-research/file-search-only agent; no M365 access.",
    )
    args = parser.parse_args()
    settings = get_settings()
    if not args.without_workiq and not settings.workiq_connection_name:
        parser.error("Set WORKIQ_CONNECTION_NAME or explicitly use --without-workiq.")
    paths = guideline_paths()

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential
    ) as project, project.get_openai_client() as openai:
        connection_id = None
        if not args.without_workiq:
            connection = project.connections.get(settings.workiq_connection_name)
            if connection.target.rstrip("/") != WORKIQ_MCP_URL:
                raise RuntimeError(
                    f"Work IQ connection must target {WORKIQ_MCP_URL}; "
                    "do not reuse a preview A2A or unrelated connection."
                )
            connection_id = connection.id

        vector_store = openai.vector_stores.create(name=VECTOR_STORE_NAME)
        file_ids: list[str] = []
        try:
            for path in paths:
                with path.open("rb") as guideline:
                    uploaded = openai.files.create(file=guideline, purpose="assistants")
                file_ids.append(uploaded.id)
                indexed = openai.vector_stores.files.create_and_poll(
                    vector_store_id=vector_store.id,
                    file_id=uploaded.id,
                )
                if indexed.status != "completed":
                    raise RuntimeError(
                        f"Indexing {path.name} {indexed.status}: {indexed.last_error}"
                    )

            agent = project.agents.create_version(
                agent_name=args.name,
                definition=create_definition(
                    settings,
                    vector_store_id=vector_store.id,
                    workiq_connection_id=connection_id,
                ),
                description=f"{DISPLAY_NAME}: read-only architecture safety workshop.",
            )
        except Exception:
            openai.vector_stores.delete(vector_store.id)
            for file_id in file_ids:
                openai.files.delete(file_id)
            raise

        print(f"Created {agent.name}, version {agent.version}")
        print(f"Vector store: {vector_store.id}")
        print(f"Uploaded files: {' '.join(file_ids)}")
        mode = "disabled (no M365 access)" if args.without_workiq else "read-only"
        print(f"Work IQ: {mode}")
        print("Keep these resource IDs for app.delete; do not delete shared connections.")


if __name__ == "__main__":
    main()
