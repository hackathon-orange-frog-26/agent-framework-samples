"""Invoke the workshop agent using a fresh, isolated conversation."""

from __future__ import annotations

import argparse
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

from .agent import AGENT_NAME, DEFAULT_QUESTION
from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--name", default=AGENT_NAME)
    parser.add_argument("--version", help="Pin the immutable version printed by app.create.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full response to stderr; may contain private tool results.",
    )
    args = parser.parse_args()
    settings = get_settings()
    reference = {"name": args.name, "type": "agent_reference"}
    if args.version:
        reference["version"] = args.version

    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential
    ) as project, project.get_openai_client() as client:
        conversation = client.conversations.create()
        try:
            response = client.responses.create(
                conversation=conversation.id,
                input=args.question,
                tool_choice="auto",
                extra_body={"agent_reference": reference},
            )
            if args.debug:
                print(response.model_dump_json(indent=2), file=sys.stderr)
            if response.status != "completed":
                raise RuntimeError(
                    f"Prompt agent response {response.status}: "
                    f"{response.error or response.incomplete_details}"
                )
            for item in response.output:
                if item.type == "mcp_call" and item.error:
                    raise RuntimeError(f"MCP tool error: {item.error}")
                if item.type == "mcp_approval_request":
                    raise RuntimeError(
                        "Unexpected MCP approval request. Create a new version with "
                        "app.create and select its version; MCP tools must use "
                        'require_approval="never".'
                    )
            print(response.output_text)
        finally:
            client.conversations.delete(conversation_id=conversation.id)


if __name__ == "__main__":
    main()
