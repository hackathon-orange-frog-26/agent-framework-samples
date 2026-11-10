from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from app import create, delete, invoke
from app.agent import (
    AGENT_NAME,
    DISPLAY_NAME,
    INSTRUCTIONS,
    MSLEARN_MCP_URL,
    SHAREPOINT_CREATE_TOOLS,
    SHAREPOINT_READ_TOOLS,
    SHAREPOINT_TOOLS,
    WORKIQ_MCP_URL,
    WORKIQ_TOOLS,
    create_definition,
)
from app.config import Settings, get_settings

SETTINGS = Settings(
    project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
    model_deployment="workshop-model",
    workiq_connection_name="workshop-workiq-mcp",
    sharepoint_connection_name="workshop-sharepoint-mcp",
)
SHAREPOINT_URL = (
    "https://agent365.svc.cloud.microsoft/agents/tenants/"
    "11111111-2222-3333-4444-555555555555/servers/mcp_SharePointRemoteServer"
)
SHAREPOINT_TENANTLESS_URL = (
    "https://agent365.svc.cloud.microsoft/agents/servers/mcp_SharePointRemoteServer"
)


def clients(monkeypatch, module, argv):
    project = MagicMock()
    project.__enter__.return_value = project
    openai = MagicMock()
    openai.__enter__.return_value = openai
    project.get_openai_client.return_value = openai
    project.connections.get.return_value = SimpleNamespace(
        target=WORKIQ_MCP_URL, id="/connections/workiq"
    )
    project.connections.get.side_effect = lambda name: (
        SimpleNamespace(target=SHAREPOINT_URL, id="/connections/sharepoint")
        if name == SETTINGS.sharepoint_connection_name
        else project.connections.get.return_value
    )
    project.agents.create_version.return_value = SimpleNamespace(
        name=AGENT_NAME, version="1"
    )
    openai.conversations.create.return_value.id = "conv_workshop"
    openai.responses.create.return_value = SimpleNamespace(
        status="completed", output_text="Architecture", output=[]
    )
    monkeypatch.setattr(module, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(module, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(module, "AIProjectClient", MagicMock(return_value=project))
    monkeypatch.setattr("sys.argv", argv)
    return project, openai


def test_sample_name_preserves_deployed_agent_id():
    assert DISPLAY_NAME == "Microsoft Enterprise Architect Prompt"
    assert INSTRUCTIONS.startswith(f"You are {DISPLAY_NAME},")
    assert AGENT_NAME == "mea-prompt-agent"


def test_definition_serializes_all_four_tools():
    definition = create_definition(
        SETTINGS,
        workiq_connection_id="/connections/workiq",
        sharepoint_connection_id="/connections/sharepoint",
        sharepoint_server_url=SHAREPOINT_URL,
    ).as_dict()

    assert definition["kind"] == "prompt"
    assert definition["model"] == "workshop-model"
    assert definition["instructions"] == INSTRUCTIONS
    assert definition["tools"] == [
        {"type": "web_search"},
        {
            "type": "mcp",
            "server_label": "MicrosoftLearn",
            "server_url": MSLEARN_MCP_URL,
            "require_approval": "never",
        },
        {
            "type": "mcp",
            "server_label": "WorkIQ",
            "server_url": WORKIQ_MCP_URL,
            "project_connection_id": "/connections/workiq",
            "allowed_tools": list(WORKIQ_TOOLS),
            "require_approval": "never",
        },
        {
            "type": "mcp",
            "server_label": "SharePoint",
            "server_url": SHAREPOINT_URL,
            "project_connection_id": "/connections/sharepoint",
            "allowed_tools": list(SHAREPOINT_TOOLS),
            "require_approval": {
                "never": {"tool_names": list(SHAREPOINT_READ_TOOLS)},
                "always": {"tool_names": list(SHAREPOINT_CREATE_TOOLS)},
            },
        },
    ]


def test_without_workiq_omits_m365_tool():
    definition = create_definition(
        SETTINGS, workiq_connection_id=None
    ).as_dict()
    assert len(definition["tools"]) == 2
    assert all(tool.get("server_label") != "WorkIQ" for tool in definition["tools"])


def test_workiq_is_read_only_and_auto_approved_by_default():
    definition = create_definition(
        SETTINGS,
        workiq_connection_id="/connections/workiq",
    ).as_dict()
    assert definition["instructions"] == INSTRUCTIONS
    assert len(definition["tools"]) == 3
    workiq_tools = [
        tool for tool in definition["tools"] if tool.get("server_url") == WORKIQ_MCP_URL
    ]
    assert workiq_tools == [{
        "type": "mcp",
        "server_label": "WorkIQ",
        "server_url": WORKIQ_MCP_URL,
        "project_connection_id": "/connections/workiq",
        "allowed_tools": list(WORKIQ_TOOLS),
        "require_approval": "never",
    }]
    assert len(WORKIQ_TOOLS) == len(set(WORKIQ_TOOLS))
    assert {"fetch", "get_schema"}.issubset(WORKIQ_TOOLS)
    assert set(WORKIQ_TOOLS) == {"search_paths", "get_schema", "fetch"}


def test_sharepoint_policy_covers_every_allowed_tool_without_overlap():
    assert set(SHAREPOINT_CREATE_TOOLS) == {
        "createSmallTextFile", "createSmallBinaryFile",
    }
    assert not set(SHAREPOINT_READ_TOOLS).intersection(SHAREPOINT_CREATE_TOOLS)
    assert set(SHAREPOINT_READ_TOOLS) | set(SHAREPOINT_CREATE_TOOLS) == set(SHAREPOINT_TOOLS)


@pytest.mark.parametrize("server,name", [
    ("WorkIQ", "fetch"), ("SharePoint", "readSmallTextFile"),
    ("SharePoint", "getFolderChildren"),
])
def test_auto_approved_reads_need_no_review_flag_or_terminal(monkeypatch, server, name):
    _, openai = clients(monkeypatch, invoke, ["invoke", "Read workshop requirements"])
    openai.responses.create.return_value.output = [
        SimpleNamespace(type="mcp_call", server_label=server, name=name, error=None),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    invoke.main()
    read_input.assert_not_called()
    assert openai.responses.create.call_count == 1
    openai.conversations.delete.assert_called_once()


def test_create_resolves_separate_sharepoint_connection(monkeypatch, capsys):
    project, _ = clients(monkeypatch, create, ["create"])
    create.main()
    assert project.connections.get.call_args_list == [
        call("workshop-workiq-mcp"), call("workshop-sharepoint-mcp"),
    ]
    tools = project.agents.create_version.call_args.kwargs["definition"].as_dict()["tools"]
    assert len(tools) == 4
    assert tools[-1]["server_label"] == "SharePoint"
    assert tools[-1]["server_url"] == SHAREPOINT_URL
    assert tools[-1]["project_connection_id"] == "/connections/sharepoint"
    assert tools[-1]["allowed_tools"] == list(SHAREPOINT_TOOLS)
    assert "approval required" in capsys.readouterr().out


@pytest.mark.parametrize("module", [create, invoke])
def test_cli_exposes_sharepoint_creation_and_m365_review_options(monkeypatch, capsys, module):
    clients(monkeypatch, module, ["sample", "--help"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert ("--without-sharepoint" if module is create else "--review-m365-tools") in output


def test_instructions_route_guidelines_to_sharepoint_without_tool_details():
    assert "SharePoint MCP: retrieve internal architecture guidelines" in INSTRUCTIONS
    assert "MicrosoftLearn MCP:" in INSTRUCTIONS
    assert "WorkIQ MCP:" in INSTRUCTIONS
    assert "file search" not in INSTRUCTIONS
    assert not any(name in INSTRUCTIONS for name in SHAREPOINT_TOOLS + WORKIQ_TOOLS)
    assert AGENT_NAME != "enterprise-architect-prompt-agent"


def test_create_only_creates_agent_version_and_prints_version(monkeypatch, capsys):
    project, openai = clients(monkeypatch, create, ["create"])

    create.main()

    assert project.connections.get.call_args_list == [
        call("workshop-workiq-mcp"), call("workshop-sharepoint-mcp"),
    ]
    project.get_openai_client.assert_not_called()
    openai.vector_stores.create.assert_not_called()
    openai.files.create.assert_not_called()
    definition = project.agents.create_version.call_args.kwargs
    assert definition["agent_name"] == AGENT_NAME
    assert definition["definition"].as_dict()["tools"][-1][
        "project_connection_id"
    ] == "/connections/sharepoint"
    output = capsys.readouterr().out
    assert "version 1" in output
    assert "Vector store:" not in output
    assert "Uploaded files:" not in output


def test_create_requires_explicit_m365_opt_out(monkeypatch):
    project, openai = clients(monkeypatch, create, ["create"])
    monkeypatch.setattr(
        create,
        "get_settings",
        lambda: Settings(SETTINGS.project_endpoint, SETTINGS.model_deployment, ""),
    )
    with pytest.raises(SystemExit) as exc:
        create.main()
    assert exc.value.code == 2
    project.agents.create_version.assert_not_called()
    openai.vector_stores.create.assert_not_called()


def test_create_without_m365_does_not_resolve_connections(monkeypatch, capsys):
    project, _ = clients(
        monkeypatch, create, ["create", "--without-workiq", "--without-sharepoint"]
    )
    create.main()
    project.connections.get.assert_not_called()
    assert len(
        project.agents.create_version.call_args.kwargs["definition"].tools
    ) == 2
    assert "disabled" in capsys.readouterr().out


def test_wrong_workiq_target_fails_before_creating_resources(monkeypatch):
    project, openai = clients(monkeypatch, create, ["create"])
    project.connections.get.return_value.target = "https://example.invalid/a2a"
    with pytest.raises(RuntimeError, match="must target"):
        create.main()
    openai.vector_stores.create.assert_not_called()
    project.agents.create_version.assert_not_called()


def test_create_failure_is_reported_without_file_operations(monkeypatch):
    project, openai = clients(monkeypatch, create, ["create"])
    project.agents.create_version.side_effect = RuntimeError("agent failed")
    with pytest.raises(RuntimeError, match="agent failed"):
        create.main()
    project.get_openai_client.assert_not_called()
    assert not openai.mock_calls


@pytest.mark.parametrize("version", [None, "7"])
def test_invoke_isolated_conversation_and_optional_version(monkeypatch, capsys, version):
    argv = ["invoke", "Design invoice automation"]
    if version:
        argv.extend(["--version", version])
    _, openai = clients(monkeypatch, invoke, argv)

    invoke.main()

    reference = {"name": AGENT_NAME, "type": "agent_reference"}
    if version:
        reference["version"] = version
    openai.responses.create.assert_called_once_with(
        conversation="conv_workshop",
        input="Design invoice automation",
        tool_choice="auto",
        extra_body={"agent_reference": reference},
    )
    openai.conversations.delete.assert_called_once_with(
        conversation_id="conv_workshop"
    )
    assert capsys.readouterr().out == "Architecture\n"


@pytest.mark.parametrize("failure", ["response", "transport", "tool", "approval"])
def test_invoke_failure_is_explicit_and_conversation_is_deleted(monkeypatch, failure):
    _, openai = clients(monkeypatch, invoke, ["invoke"])
    if failure == "response":
        openai.responses.create.return_value = SimpleNamespace(
            status="failed", error="response error", incomplete_details=None
        )
        expected = "response error"
    elif failure == "transport":
        openai.responses.create.side_effect = RuntimeError("transport error")
        expected = "transport error"
    elif failure == "tool":
        openai.responses.create.return_value.output = [
            SimpleNamespace(type="mcp_call", error="access denied")
        ]
        expected = "access denied"
    else:
        openai.responses.create.return_value.output = [
            SimpleNamespace(type="mcp_approval_request")
        ]
        expected = "Unexpected MCP approval"
    with pytest.raises(RuntimeError, match=expected):
        invoke.main()
    openai.conversations.delete.assert_called_once_with(
        conversation_id="conv_workshop"
    )


def test_debug_is_explicit_and_writes_response_to_stderr(monkeypatch, capsys):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--debug"])
    openai.responses.create.return_value = MagicMock(
        status="completed", output=[], output_text="Architecture"
    )
    openai.responses.create.return_value.model_dump_json.return_value = '{"output":[]}'
    invoke.main()
    output = capsys.readouterr()
    assert output.out == "Architecture\n"
    assert output.err == '{"output":[]}\n'


def approval_request(*, name="fetch", server="WorkIQ", request_id="approval_1"):
    return SimpleNamespace(
        type="mcp_approval_request", id=request_id, server_label=server, name=name,
        arguments=(
            '{"documentLibraryId":"library","parentFolderId":"output",'
            '"filename":"design.md","contentText":"Synthetic design"}'
            if server == "SharePoint" else '{"path":"/me/messages/workshop"}'
        ),
    )


@pytest.mark.parametrize("answer,approved", [("y", True), ("n", False), ("", False)])
def test_workiq_approval_is_explicit_and_continues_same_conversation(
    monkeypatch, capsys, answer, approved
):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-workiq-tools"])
    openai.responses.create.side_effect = [
        SimpleNamespace(status="completed", output=[approval_request()]),
        SimpleNamespace(status="completed", output_text="Reviewed result", output=[]),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    invoke.main()
    assert openai.responses.create.call_args.kwargs == {
        "conversation": "conv_workshop",
        "input": [{
            "type": "mcp_approval_response", "approve": approved,
            "approval_request_id": "approval_1",
        }],
        "tool_choice": "auto",
        "extra_body": {"agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}},
    }
    output = capsys.readouterr()
    assert "/me/messages/workshop" in output.err and "WorkIQ tool: fetch" in output.err
    assert output.out == "Reviewed result\n"
    openai.conversations.delete.assert_called_once()


@pytest.mark.parametrize("server,name,interactive", [
    ("SharePoint", "create_entity", True),
    ("MicrosoftLearn", "fetch", True),
    ("WorkIQ", "delete_entity", True),
    ("WorkIQ", "create_entity", True),
    ("WorkIQ", "do_action", True),
    ("WorkIQ", "fetch", False),
])
def test_review_rejects_unexpected_tools_and_noninteractive_approval(
    monkeypatch, server, name, interactive
):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-workiq-tools"])
    openai.responses.create.return_value.output = [approval_request(name=name, server=server)]
    monkeypatch.setattr("sys.stdin.isatty", lambda: interactive)
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match="Unexpected MCP approval|interactive terminal"):
        invoke.main()
    read_input.assert_not_called()
    assert openai.responses.create.call_count == 1
    openai.conversations.delete.assert_called_once()


def test_multiple_workiq_approval_rounds_and_call_ids(monkeypatch):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-workiq-tools"])
    openai.responses.create.side_effect = [
        SimpleNamespace(status="completed", output=[approval_request(name="get_schema")]),
        SimpleNamespace(status="completed", output=[
            approval_request(request_id="approval_2"),
            approval_request(name="fetch", request_id="approval_3"),
        ]),
        SimpleNamespace(status="completed", output=[], output_text="Done"),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["y", "y", "n"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    invoke.main()
    calls = openai.responses.create.call_args_list
    assert len(calls) == 3
    assert [
        (item["approval_request_id"], item["approve"])
        for item in calls[2].kwargs["input"]
    ] == [("approval_2", True), ("approval_3", False)]


def test_workiq_approval_round_limit_cleans_conversation(monkeypatch):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-workiq-tools"])
    openai.responses.create.return_value.output = [approval_request()]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")
    with pytest.raises(RuntimeError, match="round limit"):
        invoke.main()
    openai.conversations.delete.assert_called_once()


def test_workiq_accepts_completion_at_approval_round_limit(monkeypatch):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-workiq-tools"])
    openai.responses.create.side_effect = [
        *[SimpleNamespace(status="completed", output=[approval_request()]) for _ in range(20)],
        SimpleNamespace(status="completed", output=[], output_text="Done"),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")
    invoke.main()
    assert openai.responses.create.call_count == 21
    openai.conversations.delete.assert_called_once()


def test_delete_only_explicit_agent_version(monkeypatch):
    argv = ["delete", "--version", "1"]
    project, openai = clients(monkeypatch, delete, argv)
    delete.main()
    project.agents.delete_version.assert_called_once_with(
        agent_name=AGENT_NAME, agent_version="1"
    )
    project.get_openai_client.assert_not_called()
    assert not openai.mock_calls
    project.connections.delete.assert_not_called()


def test_settings_require_endpoint(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="FOUNDRY_PROJECT_ENDPOINT"):
        get_settings()


def test_settings_defaults_and_whitespace(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", f" {SETTINGS.project_endpoint} ")
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT", " ")
    monkeypatch.delenv("WORKIQ_CONNECTION_NAME", raising=False)
    monkeypatch.delenv("SHAREPOINT_CONNECTION_NAME", raising=False)
    settings = get_settings()
    assert settings.project_endpoint == SETTINGS.project_endpoint
    assert settings.model_deployment == "gpt-5.3-codex-2"
    assert settings.workiq_connection_name == ""
    assert settings.sharepoint_connection_name == ""


def test_settings_workiq_connection_whitespace(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", SETTINGS.project_endpoint)
    monkeypatch.setenv("WORKIQ_CONNECTION_NAME", " workshop-workiq-mcp ")
    assert get_settings().workiq_connection_name == "workshop-workiq-mcp"


def test_settings_sharepoint_connection_whitespace(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", SETTINGS.project_endpoint)
    monkeypatch.setenv("SHAREPOINT_CONNECTION_NAME", " workshop-sharepoint-mcp ")
    assert get_settings().sharepoint_connection_name == "workshop-sharepoint-mcp"


@pytest.mark.parametrize("workiq,sharepoint", [(True, False), (False, True), (False, False)])
def test_m365_servers_can_be_disabled_independently(monkeypatch, workiq, sharepoint):
    argv = ["create"]
    if not workiq:
        argv.append("--without-workiq")
    if not sharepoint:
        argv.append("--without-sharepoint")
    project, _ = clients(monkeypatch, create, argv)
    create.main()
    tools = project.agents.create_version.call_args.kwargs["definition"].as_dict()["tools"]
    labels = {tool.get("server_label") for tool in tools}
    assert ("WorkIQ" in labels) == workiq
    assert ("SharePoint" in labels) == sharepoint
    assert project.connections.get.call_count == int(workiq) + int(sharepoint)


def test_sharepoint_allowlist_excludes_destructive_and_sharing_tools():
    assert len(SHAREPOINT_TOOLS) == len(set(SHAREPOINT_TOOLS))
    assert {"readSmallTextFile", "createSmallTextFile", "createSmallBinaryFile"}.issubset(
        SHAREPOINT_TOOLS
    )
    assert not {
        "deleteFileOrFolder", "renameFileOrFolder", "moveFileOrFolder",
        "createSharingLink", "createFolder",
    }.intersection(SHAREPOINT_TOOLS)


@pytest.mark.parametrize("connection_id,url", [
    ("/connections/sharepoint", None), (None, SHAREPOINT_URL),
])
def test_sharepoint_requires_connection_and_url_together(connection_id, url):
    with pytest.raises(ValueError, match="both"):
        create_definition(
            SETTINGS, workiq_connection_id=None,
            sharepoint_connection_id=connection_id, sharepoint_server_url=url,
        )


def test_create_requires_sharepoint_configuration_or_explicit_opt_out(monkeypatch):
    project, openai = clients(monkeypatch, create, ["create"])
    monkeypatch.setattr(create, "get_settings", lambda: Settings(
        SETTINGS.project_endpoint, SETTINGS.model_deployment, SETTINGS.workiq_connection_name,
    ))
    with pytest.raises(SystemExit) as exc:
        create.main()
    assert exc.value.code == 2
    project.connections.get.assert_not_called()
    openai.vector_stores.create.assert_not_called()


@pytest.mark.parametrize("target", [
    WORKIQ_MCP_URL,
    SHAREPOINT_URL.replace("agent365.svc.cloud.microsoft", "example.invalid"),
    SHAREPOINT_URL.replace("mcp_SharePointRemoteServer", "mcp_OneDriveRemoteServer"),
    SHAREPOINT_URL.replace("11111111-2222-3333-4444-555555555555", "not-a-tenant"),
    SHAREPOINT_URL + "?extra=true",
    SHAREPOINT_TENANTLESS_URL.replace("agent365.svc.cloud.microsoft", "example.invalid"),
    SHAREPOINT_TENANTLESS_URL.replace("mcp_SharePointRemoteServer", "mcp_OneDriveRemoteServer"),
    SHAREPOINT_TENANTLESS_URL + "?extra=true",
])
def test_wrong_sharepoint_target_fails_before_creating_resources(monkeypatch, target):
    project, openai = clients(monkeypatch, create, ["create", "--without-workiq"])
    project.connections.get.side_effect = None
    project.connections.get.return_value = SimpleNamespace(
        target=target, id="/connections/sharepoint",
    )
    with pytest.raises(RuntimeError, match="SharePoint connection must"):
        create.main()
    openai.vector_stores.create.assert_not_called()
    project.agents.create_version.assert_not_called()


@pytest.mark.parametrize("url", [SHAREPOINT_URL, SHAREPOINT_TENANTLESS_URL])
@pytest.mark.parametrize("trailing_slash", ["", "/"])
def test_sharepoint_connection_target_is_accepted_and_normalized(monkeypatch, url, trailing_slash):
    project, _ = clients(monkeypatch, create, ["create", "--without-workiq"])
    project.connections.get.side_effect = None
    project.connections.get.return_value = SimpleNamespace(
        target=url + trailing_slash, id="/connections/sharepoint",
    )
    create.main()
    tools = project.agents.create_version.call_args.kwargs["definition"].as_dict()["tools"]
    assert tools[-1]["server_url"] == url


@pytest.mark.parametrize("name", ["readSmallTextFile", "createSmallTextFile", "createSmallBinaryFile"])
@pytest.mark.parametrize("answer,approved", [("y", True), ("", False)])
def test_sharepoint_approvals_continue_same_conversation(
    monkeypatch, capsys, name, answer, approved,
):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-m365-tools"])
    openai.responses.create.side_effect = [
        SimpleNamespace(status="completed", output=[approval_request(
            name=name, server="SharePoint",
        )]),
        SimpleNamespace(status="completed", output_text="Reviewed result", output=[]),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: answer)
    invoke.main()
    assert openai.responses.create.call_args.kwargs["input"] == [{
        "type": "mcp_approval_response", "approve": approved,
        "approval_request_id": "approval_1",
    }]
    assert openai.responses.create.call_args.kwargs["conversation"] == "conv_workshop"
    assert f"SharePoint tool: {name}" in capsys.readouterr().err
    openai.conversations.delete.assert_called_once()


@pytest.mark.parametrize("server,name", [
    ("SharePoint", "deleteFileOrFolder"),
    ("SharePoint", "fetch"),
    ("WorkIQ", "create_entity"),
    ("MicrosoftLearn", "readSmallTextFile"),
])
def test_mixed_approval_batch_rejected_before_any_prompt(monkeypatch, server, name):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-m365-tools"])
    openai.responses.create.return_value.output = [
        approval_request(),
        approval_request(server=server, name=name, request_id="unexpected"),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match="Unexpected MCP approval"):
        invoke.main()
    read_input.assert_not_called()
    openai.conversations.delete.assert_called_once()


def test_legacy_workiq_flag_does_not_authorize_sharepoint(monkeypatch):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-workiq-tools"])
    openai.responses.create.return_value.output = [
        approval_request(server="SharePoint", name="createSmallTextFile"),
    ]
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match="Unexpected MCP approval"):
        invoke.main()
    read_input.assert_not_called()


def test_m365_review_handles_both_servers_across_rounds(monkeypatch):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-m365-tools"])
    openai.responses.create.side_effect = [
        SimpleNamespace(status="completed", output=[
            approval_request(request_id="workiq_read"),
            approval_request(
                server="SharePoint", name="readSmallTextFile", request_id="sharepoint_read",
            ),
        ]),
        SimpleNamespace(status="completed", output=[
            approval_request(
                server="SharePoint", name="createSmallTextFile", request_id="sharepoint_create",
            ),
        ]),
        SimpleNamespace(status="completed", output=[], output_text="Done"),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["y", "y", "n"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    invoke.main()
    calls = openai.responses.create.call_args_list
    assert [
        (item["approval_request_id"], item["approve"])
        for item in calls[1].kwargs["input"]
    ] == [("workiq_read", True), ("sharepoint_read", True)]
    assert calls[2].kwargs["input"] == [{
        "type": "mcp_approval_response", "approve": False,
        "approval_request_id": "sharepoint_create",
    }]
    assert all(item.kwargs["conversation"] == "conv_workshop" for item in calls)
    openai.conversations.delete.assert_called_once()


def test_sharepoint_review_requires_interactive_terminal(monkeypatch):
    _, openai = clients(monkeypatch, invoke, ["invoke", "--review-m365-tools"])
    openai.responses.create.return_value.output = [
        approval_request(server="SharePoint", name="createSmallTextFile"),
    ]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match="interactive terminal"):
        invoke.main()
    read_input.assert_not_called()
    assert openai.responses.create.call_count == 1
    openai.conversations.delete.assert_called_once()
