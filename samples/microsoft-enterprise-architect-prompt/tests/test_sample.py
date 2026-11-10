from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import create, delete, invoke
from app.agent import (
    AGENT_NAME,
    DISPLAY_NAME,
    INSTRUCTIONS,
    MSLEARN_MCP_URL,
    WORKIQ_MCP_URL,
    create_definition,
)
from app.config import Settings, get_settings

SETTINGS = Settings(
    project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
    model_deployment="workshop-model",
    workiq_connection_name="workshop-workiq-mcp",
)
WORKIQ_TOOL_NAMES = (
    "fetch", "fetch_blob", "create_entity", "update_entity", "delete_entity",
    "do_action", "call_function", "ask", "retrieve", "list_agents",
    "get_schema", "search_paths",
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


def test_definition_serializes_workiq_and_learn_without_catalog_filters_or_approvals():
    definition = create_definition(
        SETTINGS, workiq_connection_id="/connections/workiq"
    ).as_dict()
    assert definition["kind"] == "prompt"
    assert definition["model"] == "workshop-model"
    assert definition["instructions"] == INSTRUCTIONS
    assert definition["tools"] == [{
        "type": "mcp",
        "server_label": "MicrosoftLearn",
        "server_url": MSLEARN_MCP_URL,
        "require_approval": "never",
    }, {
        "type": "mcp",
        "server_label": "WorkIQ",
        "server_url": WORKIQ_MCP_URL,
        "project_connection_id": "/connections/workiq",
        "require_approval": "never",
    }]


@pytest.mark.parametrize("connection_id", ["", " ", "\t"])
def test_definition_requires_workiq_connection(connection_id):
    with pytest.raises(ValueError, match="Work IQ requires a connection ID"):
        create_definition(SETTINGS, workiq_connection_id=connection_id)


def test_instructions_route_all_work_to_workiq_without_approval():
    assert "Use WorkIQ MCP for all Microsoft 365 work" in INSTRUCTIONS
    assert "Use MicrosoftLearn MCP to verify Azure capabilities" in INSTRUCTIONS
    assert "including SharePoint sources" in INSTRUCTIONS
    assert "without asking for tool-use\napproval or confirmation" in INSTRUCTIONS
    assert "Do not make unrelated changes" in INSTRUCTIONS
    assert "tenant-policy denials" in INSTRUCTIONS
    assert "overwrite existing files" in INSTRUCTIONS
    assert "do not send messages" not in INSTRUCTIONS
    assert "require explicit tool approval" not in INSTRUCTIONS


def test_create_only_creates_agent_version_and_prints_version(monkeypatch, capsys):
    project, openai = clients(monkeypatch, create, ["create"])
    create.main()
    project.connections.get.assert_called_once_with("workshop-workiq-mcp")
    project.get_openai_client.assert_not_called()
    openai.vector_stores.create.assert_not_called()
    openai.files.create.assert_not_called()
    kwargs = project.agents.create_version.call_args.kwargs
    assert kwargs["agent_name"] == AGENT_NAME
    assert kwargs["definition"].as_dict()["tools"] == create_definition(
        SETTINGS, workiq_connection_id="/connections/workiq"
    ).as_dict()["tools"]
    assert "Microsoft Learn and the full Work IQ MCP catalog" in kwargs["description"]
    output = capsys.readouterr().out
    assert "version 1" in output
    assert "all tool calls auto-approved" in output
    assert "Vector store:" not in output
    assert "Uploaded files:" not in output


def test_create_requires_workiq_before_resolving_connections(monkeypatch, capsys):
    project, _ = clients(monkeypatch, create, ["create"])
    monkeypatch.setattr(
        create, "get_settings",
        lambda: Settings(SETTINGS.project_endpoint, SETTINGS.model_deployment, ""),
    )
    with pytest.raises(SystemExit) as exc:
        create.main()
    assert exc.value.code == 2
    assert "Set WORKIQ_CONNECTION_NAME" in capsys.readouterr().err
    project.connections.get.assert_not_called()
    project.agents.create_version.assert_not_called()


@pytest.mark.parametrize("target", [
    "https://example.invalid/a2a",
    "https://workiq.svc.cloud.microsoft/mcp?extra=true",
    "https://learn.microsoft.com/api/mcp",
    "https://agent365.svc.cloud.microsoft/agents/servers/mcp_SharePointRemoteServer",
])
def test_wrong_workiq_target_fails_before_creating_resources(monkeypatch, target):
    project, openai = clients(monkeypatch, create, ["create"])
    project.connections.get.return_value.target = target
    with pytest.raises(RuntimeError, match="must target"):
        create.main()
    openai.vector_stores.create.assert_not_called()
    project.agents.create_version.assert_not_called()


def test_workiq_connection_accepts_trailing_slash(monkeypatch):
    project, _ = clients(monkeypatch, create, ["create"])
    project.connections.get.return_value.target = WORKIQ_MCP_URL + "/"
    create.main()
    tools = project.agents.create_version.call_args.kwargs["definition"].as_dict()["tools"]
    assert tools[-1]["server_url"] == WORKIQ_MCP_URL


@pytest.mark.parametrize("operation", ["connection", "agent"])
def test_create_failure_is_reported_without_file_operations(monkeypatch, operation):
    project, openai = clients(monkeypatch, create, ["create"])
    if operation == "connection":
        project.connections.get.side_effect = RuntimeError("connection failed")
    else:
        project.agents.create_version.side_effect = RuntimeError("agent failed")
    with pytest.raises(RuntimeError, match=f"{operation} failed"):
        create.main()
    project.get_openai_client.assert_not_called()
    assert not openai.mock_calls


@pytest.mark.parametrize("module,flag", [
    (create, "--without-workiq"),
    (create, "--without-sharepoint"),
    (invoke, "--review-workiq-tools"),
    (invoke, "--review-m365-tools"),
])
def test_removed_flags_are_rejected(monkeypatch, module, flag):
    project, _ = clients(monkeypatch, module, ["sample", flag])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    project.connections.get.assert_not_called()
    project.get_openai_client.assert_not_called()


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


@pytest.mark.parametrize("server,name", [
    *(("WorkIQ", name) for name in WORKIQ_TOOL_NAMES + ("future_tool",)),
    ("MicrosoftLearn", "microsoft_docs_search"),
    ("MicrosoftLearn", "microsoft_docs_fetch"),
    ("MicrosoftLearn", "microsoft_code_sample_search"),
])
def test_all_mcp_calls_need_no_review_flag_or_terminal(monkeypatch, server, name):
    _, openai = clients(monkeypatch, invoke, ["invoke", "Complete the requested operation"])
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


@pytest.mark.parametrize("failure", ["response", "incomplete", "transport", "tool", "approval"])
def test_invoke_failure_is_explicit_and_conversation_is_deleted(monkeypatch, capsys, failure):
    _, openai = clients(monkeypatch, invoke, ["invoke"])
    if failure in ("response", "incomplete"):
        openai.responses.create.return_value = SimpleNamespace(
            status="failed" if failure == "response" else "incomplete",
            error="response error" if failure == "response" else None,
            incomplete_details="token limit",
        )
        expected = "response error" if failure == "response" else "token limit"
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
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match=expected):
        invoke.main()
    read_input.assert_not_called()
    openai.conversations.delete.assert_called_once_with(
        conversation_id="conv_workshop"
    )
    assert openai.responses.create.call_count == 1
    assert capsys.readouterr().out == ""


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


def test_delete_only_explicit_agent_version(monkeypatch):
    project, openai = clients(monkeypatch, delete, ["delete", "--version", "1"])
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
    settings = get_settings()
    assert settings.project_endpoint == SETTINGS.project_endpoint
    assert settings.model_deployment == "gpt-5.3-codex-2"
    assert settings.workiq_connection_name == ""


def test_settings_workiq_connection_whitespace(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", SETTINGS.project_endpoint)
    monkeypatch.setenv("WORKIQ_CONNECTION_NAME", " workshop-workiq-mcp ")
    assert get_settings().workiq_connection_name == "workshop-workiq-mcp"
