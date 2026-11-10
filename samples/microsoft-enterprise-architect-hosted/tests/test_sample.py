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
import httpx2
import pytest
from agent_framework import (
    Agent, BaseChatClient, ChatResponse, ChatResponseUpdate, Content,
    FunctionInvocationLayer, Message, ResponseStream,
)
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.projects.models import AgentEndpointConfig
from mcp.server.mcpserver import MCPServer

from app import agent, delete, deploy, host, invoke
from app.config import Settings, get_settings

SETTINGS = Settings("https://example.services.ai.azure.com/api/projects/demo", "workshop-model")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    for name in (
        "FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL_DEPLOYMENT", "AZURE_AI_MODEL_DEPLOYMENT_NAME",
        "TOOLBOX_NAME", "TOOLBOX_VERSION",
    ):
        monkeypatch.delenv(name, raising=False)


def clients(monkeypatch, module, argv):
    project = MagicMock()
    project.__enter__.return_value = project
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


def approval(*, name="SharePoint___createSmallTextFile", server="agent_framework", id="approval_test"):
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


def test_toolbox_configuration_defaults_overrides_and_validation(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", SETTINGS.project_endpoint)
    assert get_settings().toolbox_name == "WorkIQToolbox"
    assert get_settings().toolbox_version == "1"
    monkeypatch.setenv("TOOLBOX_NAME", " custom-toolbox ")
    monkeypatch.setenv("TOOLBOX_VERSION", " 2 ")
    assert get_settings().toolbox_name == "custom-toolbox"
    assert get_settings().toolbox_version == "2"
    monkeypatch.setenv("TOOLBOX_VERSION", " ")
    with pytest.raises(ValueError, match="TOOLBOX_VERSION"):
        get_settings()


def test_agent_wires_workiq_toolbox_and_preserves_native_tools(monkeypatch):
    factory = MagicMock()
    client_factory = MagicMock()
    monkeypatch.setattr(agent, "Agent", factory)
    monkeypatch.setattr(agent, "FoundryChatClient", client_factory)
    toolbox_factory = MagicMock()
    monkeypatch.setattr(agent, "FoundryToolbox", toolbox_factory)
    context = MagicMock()
    context.platform_headers.return_value = {"x-agent-foundry-call-id": "opaque-call"}
    monkeypatch.setattr(agent, "get_request_context", lambda: context)
    credential = MagicMock()

    agent.create_agent(SETTINGS, credential)

    client_factory.assert_called_once_with(
        project_endpoint=SETTINGS.project_endpoint, model="workshop-model", credential=credential,
        default_headers={"x-agent-foundry-call-id": "opaque-call"},
    )
    options = factory.call_args.kwargs
    assert options["name"] == "mea-hosted-agent"
    assert "Mermaid" in options["instructions"]
    assert "never overwrite" in options["instructions"]
    assert options["default_options"] == {"store": False}
    toolbox_factory.assert_called_once_with(
        credential,
        url=f"{SETTINGS.project_endpoint}/toolboxes/WorkIQToolbox/versions/1/mcp?api-version=v1",
        name="WorkIQToolbox",
        approval_mode="always_require",
    )
    assert options["tools"][2] is toolbox_factory.return_value
    tools = [tool.as_dict() for tool in options["tools"] if tool is not toolbox_factory.return_value]
    assert tools == [
        {"type": "web_search"},
        {"type": "mcp", "server_label": "MicrosoftLearn",
         "server_url": agent.MSLEARN_MCP_URL, "require_approval": "never"},
    ]


@pytest.mark.parametrize("toolbox", ["", "WorkIQToolbox"])
def test_explicitly_disabled_toolbox_is_omitted(monkeypatch, toolbox):
    toolbox_factory = MagicMock()
    monkeypatch.setattr(agent, "FoundryToolbox", toolbox_factory)
    settings = replace(SETTINGS, toolbox_name=toolbox)
    configured = agent.create_tools(settings, MagicMock())
    assert toolbox_factory.call_count == bool(toolbox)
    tools = [tool.as_dict() for tool in configured if tool is not toolbox_factory.return_value]
    assert [tool["server_label"] for tool in tools if tool["type"] == "mcp"] == ["MicrosoftLearn"]


def test_toolbox_url_uses_configured_project_name_and_version(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(agent, "FoundryToolbox", factory)
    credential = MagicMock()
    settings = replace(
        SETTINGS, project_endpoint=SETTINGS.project_endpoint + "/",
        toolbox_name="custom-toolbox", toolbox_version="2",
    )
    agent.create_tools(settings, credential)
    factory.assert_called_once_with(
        credential,
        url=f"{SETTINGS.project_endpoint}/toolboxes/custom-toolbox/versions/2/mcp?api-version=v1",
        name="custom-toolbox",
        approval_mode="always_require",
    )
    with pytest.raises(ValueError, match="version"):
        agent.create_tools(replace(settings, toolbox_version=""), credential)


def test_deploy_requires_explicit_opt_out_for_empty_toolbox(monkeypatch, capsys):
    project, _ = clients(monkeypatch, deploy, ["deploy"])
    monkeypatch.setattr(deploy, "get_settings", lambda: replace(SETTINGS, toolbox_name=""))
    with pytest.raises(SystemExit) as exc:
        deploy.main()
    assert exc.value.code == 2
    assert "TOOLBOX_NAME" in capsys.readouterr().err
    project.agents.create_version_from_code.assert_not_called()


@pytest.mark.parametrize("private", [False, True])
def test_deploy_packages_runtime_and_routes_without_resolving_connections(monkeypatch, private):
    flags = [] if private else ["--without-toolbox"]
    project, _ = clients(monkeypatch, deploy, ["deploy", "--name", "custom-hosted", *flags])
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
        "TOOLBOX_NAME": "WorkIQToolbox" if private else "",
        "TOOLBOX_VERSION": "1",
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
    project.connections.get.assert_not_called()


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
    project, _ = clients(monkeypatch, deploy, ["deploy", "--without-toolbox"])
    project.agents.get_version.return_value = {"status": "failed", "error": "Remote build failed"}
    with pytest.raises(RuntimeError, match="Remote build failed"):
        deploy.main()
    project.agents.update_details.assert_not_called()
    code = project.agents.create_version_from_code.call_args.kwargs["code"]
    assert code.closed
    assert not Path(code.name).parent.exists()


def test_redeploy_preserves_published_protocols_and_authorization(monkeypatch):
    project, _ = clients(monkeypatch, deploy, ["deploy", "--without-toolbox"])
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
    monkeypatch.setattr(host, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(host, "DefaultAzureCredential", lambda: credential)
    monkeypatch.setattr(host, "create_agent", factory)
    monkeypatch.setattr(host, "ResponsesHostServer", server)
    host.main()
    request_factory = server.call_args.kwargs["agent"]
    assert request_factory() is not request_factory()
    factory.assert_called_with(SETTINGS, credential)
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
    with pytest.raises(RuntimeError, match="local toolbox"):
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
def test_toolbox_discovery_auth_call_id_lifecycle_and_approval(tmp_path, monkeypatch, approve):
    monkeypatch.setenv("HOME", str(tmp_path))
    methods = []
    toolbox_clients = []
    credential = MagicMock()
    credential.get_token.return_value = SimpleNamespace(token="offline-toolbox-token", expires_on=9999999999)
    mcp_server = MCPServer("offline-toolbox", subscriptions=False)

    @mcp_server.tool(name="SharePoint___createSmallTextFile")
    async def create_file(filename: str) -> str:
        assert filename == "new.md"
        return "Created"

    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/api/projects/demo/toolboxes/WorkIQToolbox/versions/1/mcp",
        json_response=True, stateless_http=True, host="example.services.ai.azure.com",
    )
    mcp_transport = httpx2.ASGITransport(app=mcp_app)

    async def transport(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == (
            f"{SETTINGS.project_endpoint}/toolboxes/WorkIQToolbox/versions/1/mcp?api-version=v1"
        )
        assert request.headers["authorization"] == "Bearer offline-toolbox-token"
        assert request.headers["x-agent-foundry-call-id"] in {"call-1", "call-2"}
        if request.method == "POST":
            body = json.loads(request.content)
            methods.append(body["method"])
            if body["method"] == "tools/call":
                assert request.headers["x-agent-foundry-call-id"] == "call-2"
                assert body["params"]["name"] == "SharePoint___createSmallTextFile"
                assert body["params"]["arguments"] == {"filename": "new.md"}
        return await mcp_transport.handle_async_request(request)

    original_init = httpx2.AsyncClient.__init__

    def init_client(self, *args, **kwargs):
        if "transport" not in kwargs:
            kwargs["transport"] = httpx2.MockTransport(transport)
            toolbox_clients.append(self)
        original_init(self, *args, **kwargs)

    class ToolboxClient(FunctionInvocationLayer, BaseChatClient):
        STORES_BY_DEFAULT = False

        def _inner_get_response(
            self, *, messages: Sequence[Message], stream: bool, options: Mapping[str, object], **kwargs: object,
        ) -> ResponseStream[ChatResponseUpdate, ChatResponse]:
            async def updates() -> AsyncIterator[ChatResponseUpdate]:
                assert options["store"] is False
                results = [
                    content for message in messages for content in message.contents
                    if content.type == "function_result"
                ]
                contents = (
                    [Content.from_text("Created" if approve else "Denied")]
                    if results else
                    [Content.from_function_call(
                        "tool_call", "SharePoint___createSmallTextFile", arguments={"filename": "new.md"},
                    )]
                )
                yield ChatResponseUpdate(role="assistant", contents=contents)

            return ResponseStream(updates(), finalizer=ChatResponse.from_updates)

    monkeypatch.setattr(httpx2.AsyncClient, "__init__", init_client)
    monkeypatch.setattr(agent, "FoundryChatClient", lambda **kwargs: ToolboxClient())

    async def scenario():
        server = ResponsesHostServer(agent=lambda: agent.create_agent(SETTINGS, credential))
        async with (
            mcp_app.router.lifespan_context(mcp_app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=server), base_url="http://test") as client,
        ):
            first = await client.post(
                "/responses", json={"input": "Create new.md", "stream": False},
                headers={"x-agent-foundry-call-id": "call-1"},
            )
            assert first.status_code == 200, first.text
            body = first.json()
            assert body["status"] == "completed", first.text
            assert body["status"] == "completed", first.text
            request = next(item for item in body["output"] if item["type"] == "mcp_approval_request")
            assert request["server_label"] == "agent_framework"
            assert request["name"] == "SharePoint___createSmallTextFile"
            assert "tools/call" not in methods
            assert all(client.is_closed for client in toolbox_clients)
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
    assert methods.count("tools/call") == int(approve)
    assert all(client.is_closed for client in toolbox_clients)
    credential.get_token.assert_called_with("https://ai.azure.com/.default")
