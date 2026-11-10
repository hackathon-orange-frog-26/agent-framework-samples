"""Invoke the hosted endpoint with optional interactive SharePoint approvals."""

from __future__ import annotations

import argparse
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses import Response
from openai.types.responses.response_input_param import McpApprovalResponse, ResponseInputParam

from .agent import AGENT_NAME, DEFAULT_QUESTION, SHAREPOINT_CREATE_TOOLS
from .config import get_settings


def review_calls(response: Response) -> ResponseInputParam:
    requests = [item for item in response.output if item.type == "mcp_approval_request"]
    for item in requests:
        if item.server_label != "SharePoint" or item.name not in SHAREPOINT_CREATE_TOOLS:
            raise RuntimeError("Unexpected MCP approval request outside the SharePoint creation allowlist.")
    if not sys.stdin.isatty():
        raise RuntimeError("SharePoint approval requires an interactive terminal; no calls were approved.")
    approvals: ResponseInputParam = []
    for item in requests:
        print(
            f"{item.server_label} tool: {item.name}\nArguments: {item.arguments}\n"
            "Review the destination, filename, content and conflict check. "
            "Approve this exact call? (y/N): ",
            file=sys.stderr, end="", flush=True,
        )
        approvals.append(McpApprovalResponse(
            type="mcp_approval_response",
            approve=input().strip().lower() == "y",
            approval_request_id=item.id,
        ))
    return approvals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--name", default=AGENT_NAME)
    parser.add_argument("--review-m365-tools", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Print full responses; may contain private data.")
    args = parser.parse_args()
    settings = get_settings()
    with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=settings.project_endpoint, credential=credential
    ) as project, project.get_openai_client(agent_name=args.name) as client:
        response = client.responses.create(input=args.question, store=True)
        approval_rounds = 0
        while True:
            if args.debug:
                print(response.model_dump_json(indent=2), file=sys.stderr)
            if response.status != "completed":
                raise RuntimeError(
                    f"Hosted agent response {response.status}: {response.error or response.incomplete_details}"
                )
            for item in response.output:
                if item.type == "mcp_call" and item.error:
                    raise RuntimeError(f"MCP tool error: {item.error}")
                if item.type == "oauth_consent_request":
                    raise RuntimeError(
                        "MCP OAuth consent is required. Complete consent in the Foundry playground "
                        "as the intended user, then retry."
                    )
            if not any(item.type == "mcp_approval_request" for item in response.output):
                break
            if not args.review_m365_tools:
                raise RuntimeError(
                    "SharePoint creation requires --review-m365-tools in an interactive terminal. "
                    "This CLI never auto-approves calls."
                )
            if approval_rounds >= 20:
                raise RuntimeError("M365 approval round limit reached; review traces before retrying.")
            approvals = review_calls(response)
            response = client.responses.create(
                previous_response_id=response.id, input=approvals, store=True,
            )
            approval_rounds += 1
        print(response.output_text)


if __name__ == "__main__":
    main()
