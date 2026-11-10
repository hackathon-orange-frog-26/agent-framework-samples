"""Invoke the workshop agent using a fresh, isolated conversation."""

from __future__ import annotations

import argparse
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.responses import Response
from openai.types.responses.response_input_param import McpApprovalResponse, ResponseInputParam

from .agent import AGENT_NAME, DEFAULT_QUESTION, SHAREPOINT_TOOLS, WORKIQ_TOOLS
from .config import get_settings


def review_m365_calls(
    response: Response, *, allow_workiq: bool, allow_sharepoint: bool,
) -> ResponseInputParam:
    """Validate the entire approval batch before prompting for any call."""
    allowed = {}
    if allow_workiq:
        allowed["WorkIQ"] = WORKIQ_TOOLS
    if allow_sharepoint:
        allowed["SharePoint"] = SHAREPOINT_TOOLS
    approvals: ResponseInputParam = []
    requests = [item for item in response.output if item.type == "mcp_approval_request"]
    for item in requests:
        if item.name not in allowed.get(item.server_label, ()):
            raise RuntimeError("Unexpected MCP approval request outside the enabled M365 allowlists.")
    if not sys.stdin.isatty():
        raise RuntimeError("M365 approval requires an interactive terminal; no calls were approved.")
    for item in requests:
        print(
            f"{item.server_label} tool: {item.name}\nArguments: {item.arguments}\n"
            "Review the path, operation, destination and content. Approve this exact call? (y/N): ",
            file=sys.stderr,
            end="",
            flush=True,
        )
        approved = input().strip().lower() == "y"
        approvals.append(
            McpApprovalResponse(
                type="mcp_approval_response",
                approve=approved,
                approval_request_id=item.id,
            )
        )
    return approvals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--name", default=AGENT_NAME)
    parser.add_argument("--version", help="Pin the immutable version printed by app.create.")
    parser.add_argument(
        "--review-m365-tools",
        action="store_true",
        help="Review explicit M365 approval requests (SharePoint creation); reads auto-approve.",
    )
    parser.add_argument(
        "--review-workiq-tools",
        action="store_true",
        help="Review only WorkIQ calls (legacy flag); excludes SharePoint.",
    )
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
            approval_rounds = 0
            while True:
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
                if not any(item.type == "mcp_approval_request" for item in response.output):
                    break
                if not (args.review_m365_tools or args.review_workiq_tools):
                    raise RuntimeError(
                        "Unexpected MCP approval request. Rerun with "
                        "--review-m365-tools in an interactive terminal. "
                        "This CLI never auto-approves calls."
                    )
                if approval_rounds >= 20:
                    raise RuntimeError("M365 approval round limit reached; review traces before retrying.")
                approvals = review_m365_calls(
                    response,
                    allow_workiq=args.review_m365_tools or args.review_workiq_tools,
                    allow_sharepoint=args.review_m365_tools,
                )
                response = client.responses.create(
                    conversation=conversation.id,
                    input=approvals,
                    tool_choice="auto",
                    extra_body={"agent_reference": reference},
                )
                approval_rounds += 1
            print(response.output_text)
        finally:
            client.conversations.delete(conversation_id=conversation.id)


if __name__ == "__main__":
    main()
