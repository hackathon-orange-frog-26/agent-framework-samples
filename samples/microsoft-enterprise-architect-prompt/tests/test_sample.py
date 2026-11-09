from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import create, delete, invoke
from app.agent import (
    AGENT_NAME,
    DISPLAY_NAME,
    INSTRUCTIONS,
    MSLEARN_MCP_URL,
    VECTOR_STORE_NAME,
    WORKIQ_MCP_URL,
    create_definition,
)
from app.config import Settings, get_settings

SETTINGS = Settings(
    project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
    model_deployment="workshop-model",
    workiq_connection_name="workshop-workiq-mcp",
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
    openai.vector_stores.create.return_value.id = "vs_workshop"
    openai.files.create.side_effect = [
        SimpleNamespace(id=f"file_{index}")
        for index in range(len(create.guideline_paths()))
    ]
    openai.vector_stores.files.create_and_poll.return_value.status = "completed"
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
        vector_store_id="vs_workshop",
        workiq_connection_id="/connections/workiq",
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
        {"type": "file_search", "vector_store_ids": ["vs_workshop"]},
        {
            "type": "mcp",
            "server_label": "WorkIQ",
            "server_url": WORKIQ_MCP_URL,
            "project_connection_id": "/connections/workiq",
            "allowed_tools": ["fetch", "get_schema"],
            "require_approval": "never",
        },
    ]


def test_without_workiq_omits_m365_tool():
    definition = create_definition(
        SETTINGS, vector_store_id="vs_workshop", workiq_connection_id=None
    ).as_dict()
    assert len(definition["tools"]) == 3
    assert all(tool.get("server_label") != "WorkIQ" for tool in definition["tools"])


def test_reuses_only_original_policy_files_not_workshop_fixtures():
    paths = create.guideline_paths()
    assert {path.name for path in paths} == {
        "governance-and-cost.md",
        "platform-security.md",
        "reliability-and-recovery.md",
    }
    assert all(
        path.parent.parent.name == "enterprise-architect-prompt-agent"
        for path in paths
    )
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures"
    assert not set(paths).intersection(fixture_dir.iterdir())
    assert AGENT_NAME != "enterprise-architect-prompt-agent"


def test_no_guidelines_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(create, "GUIDELINES_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="No Markdown guidelines"):
        create.guideline_paths()


def test_create_indexes_all_guidelines_and_prints_owned_resources(monkeypatch, capsys):
    project, openai = clients(monkeypatch, create, ["create"])

    create.main()

    project.connections.get.assert_called_once_with("workshop-workiq-mcp")
    openai.vector_stores.create.assert_called_once_with(name=VECTOR_STORE_NAME)
    count = len(create.guideline_paths())
    assert openai.files.create.call_count == count
    for index, call in enumerate(
        openai.vector_stores.files.create_and_poll.call_args_list
    ):
        assert call.kwargs == {
            "vector_store_id": "vs_workshop",
            "file_id": f"file_{index}",
        }
    definition = project.agents.create_version.call_args.kwargs
    assert definition["agent_name"] == AGENT_NAME
    assert definition["definition"].as_dict()["tools"][-1][
        "project_connection_id"
    ] == "/connections/workiq"
    output = capsys.readouterr().out
    assert "version 1" in output and "vs_workshop" in output
    assert all(f"file_{index}" in output for index in range(count))
    openai.files.delete.assert_not_called()
    openai.vector_stores.delete.assert_not_called()


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


def test_create_without_workiq_does_not_resolve_connection(monkeypatch, capsys):
    project, _ = clients(monkeypatch, create, ["create", "--without-workiq"])
    create.main()
    project.connections.get.assert_not_called()
    assert len(
        project.agents.create_version.call_args.kwargs["definition"].tools
    ) == 3
    assert "disabled" in capsys.readouterr().out


def test_wrong_workiq_target_fails_before_creating_resources(monkeypatch):
    project, openai = clients(monkeypatch, create, ["create"])
    project.connections.get.return_value.target = "https://example.invalid/a2a"
    with pytest.raises(RuntimeError, match="must target"):
        create.main()
    openai.vector_stores.create.assert_not_called()
    project.agents.create_version.assert_not_called()


@pytest.mark.parametrize("stage", ["upload", "index", "agent"])
def test_create_failure_cleans_owned_store_and_uploaded_files(monkeypatch, stage):
    project, openai = clients(monkeypatch, create, ["create"])
    count = len(create.guideline_paths())
    if stage == "upload":
        openai.files.create.side_effect = RuntimeError("upload failed")
        uploaded_count = 0
    elif stage == "index":
        openai.vector_stores.files.create_and_poll.side_effect = RuntimeError(
            "index failed"
        )
        uploaded_count = 1
    else:
        project.agents.create_version.side_effect = RuntimeError("agent failed")
        uploaded_count = count
    with pytest.raises(RuntimeError, match=f"{stage} failed"):
        create.main()
    openai.vector_stores.delete.assert_called_once_with("vs_workshop")
    assert [call.args[0] for call in openai.files.delete.call_args_list] == [
        f"file_{index}" for index in range(uploaded_count)
    ]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_unsuccessful_indexing_never_creates_agent(monkeypatch, status):
    project, openai = clients(monkeypatch, create, ["create"])
    indexed = openai.vector_stores.files.create_and_poll.return_value
    indexed.status = status
    indexed.last_error = "unsupported file"
    with pytest.raises(RuntimeError, match="unsupported file"):
        create.main()
    project.agents.create_version.assert_not_called()
    openai.vector_stores.delete.assert_called_once_with("vs_workshop")
    openai.files.delete.assert_called_once_with("file_0")


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


@pytest.mark.parametrize("delete_data", [True, False])
def test_delete_only_explicit_resources(monkeypatch, delete_data):
    argv = ["delete", "--version", "1"]
    if delete_data:
        argv.extend(["--vector-store", "vs_workshop", "--files", "file_0", "file_1"])
    project, openai = clients(monkeypatch, delete, argv)
    delete.main()
    project.agents.delete_version.assert_called_once_with(
        agent_name=AGENT_NAME, agent_version="1"
    )
    if delete_data:
        openai.vector_stores.delete.assert_called_once_with("vs_workshop")
        assert [call.args[0] for call in openai.files.delete.call_args_list] == [
            "file_0",
            "file_1",
        ]
    else:
        openai.vector_stores.delete.assert_not_called()
        openai.files.delete.assert_not_called()
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
