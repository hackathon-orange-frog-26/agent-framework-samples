from __future__ import annotations

import asyncio
import json
import runpy
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from zipfile import ZipFile

import httpx
import pytest
from agent_framework import Agent, BaseChatClient, ChatResponse, ChatResponseUpdate, Content, Message, ResponseStream
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.projects.models import AgentEndpointConfig
from openai import AsyncOpenAI

from app import agent, delete, deploy, host, invoke
from app.config import Settings, get_settings

SETTINGS = Settings("https://example.services.ai.azure.com/api/projects/demo", "workshop-model")
SHAREPOINT_URL = (
    "https://agent365.svc.cloud.microsoft/agents/tenants/"
    "11111111-2222-3333-4444-555555555555/servers/mcp_SharePointRemoteServer"
)
PRIVATE_SETTINGS = replace(
    SETTINGS, workiq_connection_id="/connections/workiq",
    sharepoint_connection_id="/connections/sharepoint", sharepoint_server_url=SHAREPOINT_URL,
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    for name in (
        "FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL_DEPLOYMENT", "AZURE_AI_MODEL_DEPLOYMENT_NAME",
        "WORKIQ_CONNECTION_NAME", "SHAREPOINT_CONNECTION_NAME",
        "WORKIQ_CONNECTION_ID", "SHAREPOINT_CONNECTION_ID", "SHAREPOINT_SERVER_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def clients(monkeypatch, module, argv):
    project = MagicMock()
    project.__enter__.return_value = project
    project.connections.get.side_effect = lambda name: SimpleNamespace(
        target=SHAREPOINT_URL if name == "sharepoint" else agent.WORKIQ_MCP_URL,
        id=f"/connections/{name}",
    )
    project.agents.create_version_from_code.return_value = SimpleNamespace(
        name=agent.AGENT_NAME, version="3",
    )
    project.agents.get_version.return_value = {"status": "active"}
    project.agents.get.return_value = SimpleNamespace(agent_endpoint=None)
    client = project.get_openai_client.return_value.__enter__.return_value
    client.responses.create.return_value = response()
    monkeypatch.setattr(module, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(module, "DefaultAzureCredential", MagicMock())
    monkeypatch.setattr(module, "AIProjectClient", MagicMock(return_value=project))
    monkeypatch.setattr("sys.argv", argv)
    return project, client


def response(*output, status="completed", id="resp_test"):
    return SimpleNamespace(
        id=id, status=status, output=list(output), output_text="Architecture",
        error="Access denied" if status != "completed" else None, incomplete_details=None,
    )


def approval(*, name="createSmallTextFile", server="SharePoint", id="approval_test"):
    return SimpleNamespace(
        type="mcp_approval_request", id=id, name=name, server_label=server,
        arguments='{"filename":"new.md","contentText":"Synthetic review"}',
    )


def test_configuration_requires_endpoint_and_supports_hosted_model(monkeypatch):
    with pytest.raises(RuntimeError, match="FOUNDRY_PROJECT_ENDPOINT"):
        get_settings()
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", SETTINGS.project_endpoint)
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "hosted-model")
    assert get_settings().model_deployment == "hosted-model"
    monkeypatch.setenv("FOUNDRY_MODEL_DEPLOYMENT", " local-model ")
    assert get_settings().model_deployment == "local-model"
    monkeypatch.setenv("SHAREPOINT_CONNECTION_ID", "/connections/sharepoint")
    with pytest.raises(ValueError, match="both"):
        get_settings()
    monkeypatch.setenv("SHAREPOINT_SERVER_URL", SHAREPOINT_URL + "/")
    assert get_settings().sharepoint_server_url == SHAREPOINT_URL


def test_agent_wires_native_foundry_tools_not_application_mcp(monkeypatch):
    factory = MagicMock()
    client_factory = MagicMock()
    monkeypatch.setattr(agent, "Agent", factory)
    monkeypatch.setattr(agent, "FoundryChatClient", client_factory)
    context = MagicMock()
    context.platform_headers.return_value = {"x-agent-foundry-call-id": "opaque-call"}
    monkeypatch.setattr(agent, "get_request_context", lambda: context)
    credential = MagicMock()

    agent.create_agent(PRIVATE_SETTINGS, credential)

    client_factory.assert_called_once_with(
        project_endpoint=SETTINGS.project_endpoint, model="workshop-model", credential=credential,
        default_headers={"x-agent-foundry-call-id": "opaque-call"},
    )
    options = factory.call_args.kwargs
    assert options["name"] == "mea-hosted-agent"
    assert "Mermaid" in options["instructions"]
    assert "never overwrite" in options["instructions"]
    tools = [tool.as_dict() for tool in options["tools"]]
    assert tools[:2] == [
        {"type": "web_search"},
        {"type": "mcp", "server_label": "MicrosoftLearn",
         "server_url": agent.MSLEARN_MCP_URL, "require_approval": "never"},
    ]
    assert tools[2] == {
        "type": "mcp", "server_label": "WorkIQ", "server_url": agent.WORKIQ_MCP_URL,
        "project_connection_id": "/connections/workiq",
        "allowed_tools": ["search_paths", "get_schema", "fetch"], "require_approval": "never",
    }
    assert tools[3] == {
        "type": "mcp", "server_label": "SharePoint", "server_url": SHAREPOINT_URL,
        "project_connection_id": "/connections/sharepoint",
        "allowed_tools": list(agent.SHAREPOINT_TOOLS),
        "require_approval": {
            "never": {"tool_names": list(agent.SHAREPOINT_READ_TOOLS)},
            "always": {"tool_names": ["createSmallTextFile", "createSmallBinaryFile"]},
        },
    }


@pytest.mark.parametrize("workiq,sharepoint,labels", [
    ("", "", ["MicrosoftLearn"]),
    ("/connections/workiq", "", ["MicrosoftLearn", "WorkIQ"]),
    ("", "/connections/sharepoint", ["MicrosoftLearn", "SharePoint"]),
])
def test_explicitly_disabled_private_tools_are_omitted(workiq, sharepoint, labels):
    settings = replace(
        PRIVATE_SETTINGS, workiq_connection_id=workiq, sharepoint_connection_id=sharepoint,
        sharepoint_server_url=SHAREPOINT_URL if sharepoint else "",
    )
    tools = [tool.as_dict() for tool in agent.create_tools(settings)]
    assert [tool["server_label"] for tool in tools if tool["type"] == "mcp"] == labels


@pytest.mark.parametrize("url", [
    "https://evil.example/servers/mcp_SharePointRemoteServer",
    SHAREPOINT_URL.replace("11111111-2222-3333-4444-555555555555", "not-a-uuid"),
    SHAREPOINT_URL.replace("mcp_SharePointRemoteServer", "mcp_OneDriveRemoteServer"),
    SHAREPOINT_URL + "?token=wrong",
])
def test_invalid_sharepoint_target_rejected_before_upload(monkeypatch, url):
    project, _ = clients(monkeypatch, deploy, ["deploy"])
    project.connections.get.side_effect = None
    project.connections.get.return_value = SimpleNamespace(target=url, id="/connections/sharepoint")
    with pytest.raises(ValueError, match="SharePoint"):
        deploy.resolve_connections(project, SETTINGS, workiq_name="", sharepoint_name="sharepoint")
    project.agents.create_version_from_code.assert_not_called()


def test_connections_validate_workiq_and_accept_tenantless_sharepoint():
    project = MagicMock()
    project.connections.get.return_value = SimpleNamespace(target="https://example.com", id="wrong")
    with pytest.raises(ValueError, match="Work IQ"):
        deploy.resolve_connections(project, SETTINGS, workiq_name="workiq", sharepoint_name="")
    url = "https://agent365.svc.cloud.microsoft/agents/servers/mcp_SharePointRemoteServer"
    project.connections.get.return_value = SimpleNamespace(target=url, id="/connections/sharepoint")
    settings = deploy.resolve_connections(project, PRIVATE_SETTINGS, workiq_name="", sharepoint_name="sharepoint")
    assert settings.sharepoint_server_url == url
    assert not settings.workiq_connection_id


@pytest.mark.parametrize("flags,missing", [
    ([], "WORKIQ_CONNECTION_NAME"),
    (["--without-workiq"], "SHAREPOINT_CONNECTION_NAME"),
])
def test_deploy_requires_explicit_opt_out(monkeypatch, capsys, flags, missing):
    project, _ = clients(monkeypatch, deploy, ["deploy", *flags])
    with pytest.raises(SystemExit) as exc:
        deploy.main()
    assert exc.value.code == 2
    assert missing in capsys.readouterr().err
    project.agents.create_version_from_code.assert_not_called()


@pytest.mark.parametrize("private", [False, True])
def test_deploy_packages_runtime_resolves_connections_and_routes(monkeypatch, private):
    flags = [] if private else ["--without-workiq", "--without-sharepoint"]
    project, _ = clients(monkeypatch, deploy, ["deploy", "--name", "custom-hosted", *flags])
    if private:
        monkeypatch.setenv("WORKIQ_CONNECTION_NAME", "workiq")
        monkeypatch.setenv("SHAREPOINT_CONNECTION_NAME", "sharepoint")

    deploy.main()

    upload = project.agents.create_version_from_code.call_args.kwargs
    assert upload["agent_name"] == "custom-hosted"
    assert upload["code"].closed
    assert not Path(upload["code"].name).parent.exists()
    definition = upload["definition"].as_dict()
    assert definition["kind"] == "hosted"
    assert definition["protocol_versions"] == [{"protocol": "responses", "version": "2.0.0"}]
    assert definition["code_configuration"] == {
        "runtime": "python_3_14", "entry_point": ["python", "main.py"],
        "dependency_resolution": "remote_build",
    }
    assert definition["environment_variables"] == {
        "FOUNDRY_PROJECT_ENDPOINT": SETTINGS.project_endpoint,
        "AZURE_AI_MODEL_DEPLOYMENT_NAME": "workshop-model",
        "WORKIQ_CONNECTION_ID": "/connections/workiq" if private else "",
        "SHAREPOINT_CONNECTION_ID": "/connections/sharepoint" if private else "",
        "SHAREPOINT_SERVER_URL": SHAREPOINT_URL if private else "",
    }
    project.agents.get_version.assert_called_once_with(agent_name="custom-hosted", agent_version="3")
    route = project.agents.update_details.call_args.kwargs
    assert route["agent_name"] == "custom-hosted"
    assert route["agent_endpoint"].as_dict() == {
        "version_selector": {"version_selection_rules": [
            {"type": "FixedRatio", "agent_version": "3", "traffic_percentage": 100},
        ]},
        "protocol_configuration": {"responses": {}},
    }
    project.agents.create_version.assert_not_called()


def test_zip_allowlist_excludes_secrets_and_entry_point_runs_host(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parent.parent
    staged = tmp_path / "source"
    expected = {
        "main.py", "requirements.txt", "app/__init__.py",
        "app/agent.py", "app/config.py", "app/host.py",
    }
    for name in expected:
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
    (staged / ".env").write_text("SECRET=must-not-upload")
    (staged / "app" / "token.json").write_text("must-not-upload")
    zip_path = tmp_path / "agent.zip"
    deploy.create_code_zip(staged, zip_path)
    with ZipFile(zip_path) as archive:
        assert set(archive.namelist()) == expected
    main = MagicMock()
    monkeypatch.setattr(host, "main", main)
    runpy.run_path(str(source / "main.py"), run_name="__main__")
    main.assert_called_once_with()


def test_failed_build_does_not_replace_routing_and_cleans_zip(monkeypatch):
    project, _ = clients(monkeypatch, deploy, ["deploy", "--without-workiq", "--without-sharepoint"])
    project.agents.get_version.return_value = {"status": "failed", "error": "Remote build failed"}
    with pytest.raises(RuntimeError, match="Remote build failed"):
        deploy.main()
    project.agents.update_details.assert_not_called()
    code = project.agents.create_version_from_code.call_args.kwargs["code"]
    assert code.closed
    assert not Path(code.name).parent.exists()


def test_redeploy_preserves_published_protocols_and_authorization(monkeypatch):
    project, _ = clients(monkeypatch, deploy, ["deploy", "--without-workiq", "--without-sharepoint"])
    existing = AgentEndpointConfig({
        "protocol_configuration": {"activity": {}, "responses": {}},
        "authorization_schemes": [{"type": "BotServiceTenant"}],
    })
    project.agents.get.return_value = SimpleNamespace(agent_endpoint=existing)
    deploy.main()
    endpoint = project.agents.update_details.call_args.kwargs["agent_endpoint"].as_dict()
    assert endpoint["protocol_configuration"] == {"activity": {}, "responses": {}}
    assert endpoint["authorization_schemes"] == [{"type": "BotServiceTenant"}]


def test_provisioning_wait_and_timeout(monkeypatch):
    project = MagicMock()
    project.agents.get_version.side_effect = [{"status": "creating"}, {"status": "active"}]
    monkeypatch.setattr(deploy.time, "sleep", MagicMock())
    deploy.wait_until_active(project, agent.AGENT_NAME, "3")
    deploy.time.sleep.assert_called_once_with(5)
    monkeypatch.setattr(deploy.time, "monotonic", MagicMock(side_effect=[0, 0, 601]))
    project.agents.get_version.side_effect = None
    project.agents.get_version.return_value = {"status": "creating"}
    with pytest.raises(TimeoutError):
        deploy.wait_until_active(project, agent.AGENT_NAME, "3")


def test_host_factory_is_request_scoped_and_closes_credential(monkeypatch):
    credential = MagicMock()
    credential.__enter__.return_value = credential
    factory = MagicMock(side_effect=[MagicMock(), MagicMock()])
    server = MagicMock()
    monkeypatch.setattr(host, "get_settings", lambda: PRIVATE_SETTINGS)
    monkeypatch.setattr(host, "DefaultAzureCredential", lambda: credential)
    monkeypatch.setattr(host, "create_agent", factory)
    monkeypatch.setattr(host, "ResponsesHostServer", server)
    host.main()
    request_factory = server.call_args.kwargs["agent"]
    assert request_factory() is not request_factory()
    factory.assert_called_with(PRIVATE_SETTINGS, credential)
    server.return_value.run.assert_called_once_with()
    credential.__exit__.assert_called_once()


@pytest.mark.parametrize("approve", [True, False])
def test_invoke_continues_hosted_approval_with_exact_decision(monkeypatch, approve, capsys):
    project, client = clients(monkeypatch, invoke, ["invoke", "--review-m365-tools", "Create a new file"])
    client.responses.create.side_effect = [response(approval()), response(id="resp_done")]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "y" if approve else "")

    invoke.main()

    project.get_openai_client.assert_called_once_with(agent_name=agent.AGENT_NAME)
    first, continuation = client.responses.create.call_args_list
    assert first.kwargs == {"input": "Create a new file", "store": True}
    assert continuation.kwargs == {
        "previous_response_id": "resp_test", "store": True,
        "input": [{"type": "mcp_approval_response", "approve": approve, "approval_request_id": "approval_test"}],
    }
    assert "Architecture" in capsys.readouterr().out


@pytest.mark.parametrize("interactive,flag", [(True, False), (False, True)])
def test_invoke_never_automatically_approves(monkeypatch, interactive, flag):
    _, client = clients(monkeypatch, invoke, ["invoke", *(["--review-m365-tools"] if flag else [])])
    client.responses.create.return_value = response(approval())
    monkeypatch.setattr("sys.stdin.isatty", lambda: interactive)
    read_input = MagicMock()
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match="interactive"):
        invoke.main()
    assert client.responses.create.call_count == 1
    read_input.assert_not_called()


def test_approval_batch_is_validated_before_any_prompt(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    read_input = MagicMock(return_value="y")
    monkeypatch.setattr("builtins.input", read_input)
    with pytest.raises(RuntimeError, match="allowlist"):
        invoke.review_calls(response(approval(), approval(name="do_action", server="WorkIQ")))
    read_input.assert_not_called()


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_invoke_reports_incomplete_and_failed_responses(monkeypatch, status):
    _, client = clients(monkeypatch, invoke, ["invoke"])
    client.responses.create.return_value = response(status=status)
    with pytest.raises(RuntimeError, match="Access denied"):
        invoke.main()


def test_invoke_reports_mcp_errors_without_claiming_success(monkeypatch):
    _, client = clients(monkeypatch, invoke, ["invoke"])
    client.responses.create.return_value = response(SimpleNamespace(type="mcp_call", error="Tenant denial"))
    with pytest.raises(RuntimeError, match="Tenant denial"):
        invoke.main()


def test_delete_removes_only_selected_agent(monkeypatch):
    project, _ = clients(monkeypatch, delete, ["delete", "--name", "custom-hosted"])
    delete.main()
    project.agents.delete.assert_called_once_with(agent_name="custom-hosted")
    project.connections.delete.assert_not_called()


class ApprovalClient(BaseChatClient):
    STORES_BY_DEFAULT = False

    def __init__(self):
        super().__init__()
        self.decisions: list[bool] = []

    def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool, options: Mapping[str, object], **kwargs: object,
    ) -> ResponseStream[ChatResponseUpdate, ChatResponse]:
        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            decisions = [
                content for message in messages for content in message.contents
                if content.type == "function_approval_response"
            ]
            if decisions:
                self.decisions.append(decisions[-1].approved)
                contents = [Content.from_text("Created" if decisions[-1].approved else "Denied; no file created")]
            else:
                call = Content.from_function_call(
                    "provider_call", "createSmallTextFile", arguments={"filename": "new.md"},
                    hosted=True, additional_properties={"server_label": "SharePoint"},
                )
                contents = [Content.from_function_approval_request("provider_approval", call)]
            yield ChatResponseUpdate(role="assistant", contents=contents)

        return ResponseStream(updates(), finalizer=ChatResponse.from_updates)


@pytest.mark.parametrize("approve", [True, False])
def test_real_responses_host_round_trips_native_approval(tmp_path, monkeypatch, approve):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def scenario():
        chat_clients: list[ApprovalClient] = []

        def factory():
            client = ApprovalClient()
            chat_clients.append(client)
            return Agent(client=client, name=agent.AGENT_NAME)

        server = ResponsesHostServer(agent=factory)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server), base_url="http://test") as client:
            ready = await client.get("/readiness")
            assert ready.status_code == 200
            first = await client.post("/responses", json={"input": "Create new.md", "stream": False, "store": True})
            assert first.status_code == 200, first.text
            body = first.json()
            request = next(item for item in body["output"] if item["type"] == "mcp_approval_request")
            assert request["server_label"] == "SharePoint"
            assert request["name"] == "createSmallTextFile"
            assert chat_clients[0].decisions == []
            second = await client.post("/responses", json={
                "previous_response_id": body["id"], "stream": False, "store": True,
                "input": [{"type": "mcp_approval_response", "approval_request_id": request["id"], "approve": approve}],
            })
            assert second.status_code == 200, second.text
            assert second.json()["status"] == "completed", second.text
            assert chat_clients[1].decisions == [approve]
            assert "Created" in second.text if approve else "Denied; no file created" in second.text
            third = await client.post("/responses", json={"input": "Another user", "stream": False, "store": False})
            assert third.status_code == 200, third.text
            assert chat_clients[2].decisions == []
        assert len(chat_clients) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("approve", [True, False])
def test_native_foundry_client_serializes_tools_and_replays_approval(tmp_path, monkeypatch, approve):
    monkeypatch.setenv("HOME", str(tmp_path))
    payloads = []

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payloads.append(body)
        assert request.headers["x-agent-foundry-call-id"] == f"call-{len(payloads)}"
        assert "x-agent-user-id" not in request.headers
        decisions = [item for item in body["input"] if item.get("type") == "mcp_approval_response"]
        if decisions:
            assert decisions == [{
                "type": "mcp_approval_response", "approval_request_id": "provider_approval",
                "approve": approve,
            }]
            output = {
                "type": "message", "id": "msg_provider", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "Created" if approve else "Denied", "annotations": []}],
            }
        else:
            output = {
                "type": "mcp_approval_request", "id": "provider_approval",
                "name": "createSmallTextFile", "server_label": "SharePoint",
                "arguments": '{"filename":"new.md","contentText":"Synthetic"}',
            }
        result = {
            "id": f"resp_provider_{len(payloads)}", "object": "response", "created_at": 1,
            "status": "completed", "model": "workshop-model", "output": [output],
            "usage": None,
        }
        events = [
            {"type": "response.output_item.added", "output_index": 0, "item": output},
        ]
        if decisions:
            events.append({
                "type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                "item_id": "msg_provider", "delta": "Created" if approve else "Denied",
            })
        events.extend([
            {"type": "response.output_item.done", "output_index": 0, "item": output},
            {"type": "response.completed", "response": result},
        ])
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    def create_client(**kwargs):
        project = MagicMock()
        project.get_openai_client.return_value = AsyncOpenAI(
            api_key="offline-test", base_url="https://foundry.example/openai/v1/",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            default_headers=kwargs["default_headers"],
        )
        return FoundryChatClient(project_client=project, model=kwargs["model"])

    monkeypatch.setattr(agent, "FoundryChatClient", create_client)

    async def scenario():
        server = ResponsesHostServer(agent=lambda: agent.create_agent(PRIVATE_SETTINGS, MagicMock()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server), base_url="http://test") as client:
            first = await client.post(
                "/responses", json={"input": "Create new.md", "stream": False},
                headers={"x-agent-foundry-call-id": "call-1"},
            )
            assert first.status_code == 200, first.text
            body = first.json()
            request = next(item for item in body["output"] if item["type"] == "mcp_approval_request")
            second = await client.post(
                "/responses", headers={"x-agent-foundry-call-id": "call-2"},
                json={
                    "previous_response_id": body["id"], "stream": False,
                    "input": [{
                        "type": "mcp_approval_response", "approval_request_id": request["id"], "approve": approve,
                    }],
                },
            )
            assert second.status_code == 200, second.text
            assert second.json()["status"] == "completed", second.text
            text = "".join(
                content.get("text", "") for item in second.json()["output"]
                if item["type"] == "message" for content in item["content"]
            )
            assert text == ("Created" if approve else "Denied")

    asyncio.run(scenario())
    assert len(payloads) == 2
    expected_tools = [tool.as_dict() for tool in agent.create_tools(PRIVATE_SETTINGS)]
    for payload in payloads:
        assert payload["tools"] == expected_tools
        assert payload["model"] == "workshop-model"
        assert payload["store"] is False
