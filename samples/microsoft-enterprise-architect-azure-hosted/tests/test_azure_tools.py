from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.core.pipeline.transport import AsyncHttpResponse, AsyncHttpTransport
from azure.identity.aio import ManagedIdentityCredential

from app import azure_tools, deploy
from app.azure_tools import AzureResourceGroupTools
from app.config import Settings, get_settings

SETTINGS = Settings(
    "https://example.services.ai.azure.com/api/projects/demo", "model",
    azure_subscription_id="11111111-2222-3333-4444-555555555555",
)


def group(name="mea-agent-demo", location="eastus", state="Succeeded"):
    return SimpleNamespace(
        id=f"/subscriptions/{SETTINGS.azure_subscription_id}/resourceGroups/{name}",
        name=name, location=location, tags={"owner": "keep"},
        properties=SimpleNamespace(provisioning_state=state),
    )


@pytest.fixture
def tools(monkeypatch):
    credential = AsyncMock()
    credential.__aenter__.return_value = credential
    factory = MagicMock(return_value=credential)
    client = AsyncMock()
    client.__aenter__.return_value = client
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(azure_tools, "ResourceManagementClient", constructor)
    return AzureResourceGroupTools(SETTINGS, factory), client, factory, constructor


def test_context_is_nonsecret_and_operator_configured(tools):
    tool, _, factory, _ = tools
    context = tool.azure_deployment_context()
    assert context["subscription_id"] == SETTINGS.azure_subscription_id
    assert context["resource_group_prefix"] == "mea-agent-"
    assert context["location"] == "eastus"
    assert "ManagedIdentityCredential" in context["authentication"]
    factory.assert_not_called()


@pytest.mark.parametrize("operation", ["get_resource_group", "deploy_resource_group"])
@pytest.mark.parametrize("name", [
    "production", "mea-agent-", "mea-agent-../bad", "mea-agent-a/b", "mea-agent-a?x",
    "mea-agent-" + "a" * 81, "MEA-agent-demo", "mea-agent-\u00e4",
])
def test_out_of_boundary_names_fail_before_authentication(tools, operation, name):
    tool, _, factory, _ = tools
    with pytest.raises(ValueError, match="Resource group name"):
        asyncio.run(getattr(tool, operation)(name))
    factory.assert_not_called()


def test_create_reads_back_and_closes_clients(tools):
    tool, client, factory, constructor = tools
    client.resource_groups.get.side_effect = [ResourceNotFoundError("missing"), group()]
    result = asyncio.run(tool.deploy_resource_group("mea-agent-demo"))
    assert result["outcome"] == "created_and_verified"
    assert result["id"] == group().id
    constructor.assert_called_once_with(factory.return_value, SETTINGS.azure_subscription_id)
    name, body = client.resource_groups.create_or_update.call_args.args
    assert name == "mea-agent-demo"
    assert body.location == "eastus"
    assert body.tags == {"sample": "microsoft-enterprise-architect-azure-hosted"}
    assert client.resource_groups.get.await_count == 2
    client.__aexit__.assert_awaited_once()
    factory.return_value.__aexit__.assert_awaited_once()


def test_existing_group_is_not_modified(tools):
    tool, client, _, _ = tools
    client.resource_groups.get.return_value = group()
    result = asyncio.run(tool.deploy_resource_group("mea-agent-demo"))
    assert result["outcome"] == "existing_unchanged"
    assert result["tags"] == {"owner": "keep"}
    client.resource_groups.create_or_update.assert_not_called()


def test_region_conflict_is_not_modified(tools):
    tool, client, _, _ = tools
    client.resource_groups.get.return_value = group(location="westus")
    with pytest.raises(ValueError, match="different region"):
        asyncio.run(tool.deploy_resource_group("mea-agent-demo"))
    client.resource_groups.create_or_update.assert_not_called()


@pytest.mark.parametrize("error", [
    HttpResponseError("RBAC denied"), ClientAuthenticationError("Identity unavailable"),
])
def test_authentication_and_authorization_failures_do_not_trigger_writes(tools, error):
    tool, client, factory, _ = tools
    client.resource_groups.get.side_effect = error
    with pytest.raises(type(error), match=str(error)):
        asyncio.run(tool.deploy_resource_group("mea-agent-demo"))
    client.resource_groups.create_or_update.assert_not_called()
    factory.return_value.__aexit__.assert_awaited_once()


def test_policy_denial_is_not_reported_as_success(tools):
    tool, client, _, _ = tools
    client.resource_groups.get.side_effect = ResourceNotFoundError("missing")
    client.resource_groups.create_or_update.side_effect = HttpResponseError("RequestDisallowedByPolicy")
    with pytest.raises(HttpResponseError, match="RequestDisallowedByPolicy"):
        asyncio.run(tool.deploy_resource_group("mea-agent-demo"))
    assert client.resource_groups.get.await_count == 1


@pytest.mark.parametrize("readback", [
    group(state="Failed"), group(location="westus"), ResourceNotFoundError("missing after write"),
])
def test_readback_failure_never_claims_verified_creation(tools, readback):
    tool, client, _, _ = tools
    client.resource_groups.get.side_effect = [ResourceNotFoundError("missing"), readback]
    with pytest.raises((RuntimeError, ResourceNotFoundError)):
        asyncio.run(tool.deploy_resource_group("mea-agent-demo"))


def test_get_returns_arm_metadata(tools):
    tool, client, _, _ = tools
    client.resource_groups.get.return_value = group()
    assert asyncio.run(tool.get_resource_group("mea-agent-demo"))["id"] == group().id
    client.resource_groups.get.assert_awaited_once_with("mea-agent-demo")


def test_list_excludes_other_names(tools):
    tool, client, _, _ = tools

    async def groups():
        for item in [group(), group(name="production")]:
            yield item

    client.resource_groups.list = MagicMock(return_value=groups())
    result = asyncio.run(tool.list_resource_groups())
    assert [item["name"] for item in result] == ["mea-agent-demo"]


@pytest.mark.parametrize("changes", [
    {"azure_subscription_id": ""}, {"azure_subscription_id": "../other"},
    {"resource_group_prefix": ""}, {"resource_group_prefix": "production"},
    {"resource_group_location": "East US"}, {"resource_group_location": ""},
])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        AzureResourceGroupTools(replace(SETTINGS, **changes), MagicMock())


def test_azure_environment_is_loaded(monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", SETTINGS.project_endpoint)
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SETTINGS.azure_subscription_id)
    monkeypatch.setenv("AZURE_RESOURCE_GROUP_PREFIX", "workshop-")
    monkeypatch.setenv("AZURE_RESOURCE_GROUP_LOCATION", "westus")
    settings = get_settings()
    settings.validate_azure()
    assert settings.azure_subscription_id == SETTINGS.azure_subscription_id
    assert settings.resource_group_prefix == "workshop-"
    assert settings.resource_group_location == "westus"


def test_deploy_rejects_missing_subscription_before_upload(monkeypatch):
    monkeypatch.setattr(deploy, "get_settings", lambda: replace(SETTINGS, azure_subscription_id=""))
    monkeypatch.setattr("sys.argv", ["deploy"])
    factory = MagicMock()
    monkeypatch.setattr(deploy, "AIProjectClient", factory)
    with pytest.raises(ValueError, match="AZURE_SUBSCRIPTION_ID"):
        deploy.main()
    factory.assert_not_called()


def test_real_managed_identity_and_arm_clients_use_agent_token_service(monkeypatch):
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://hosted-token-service.test/token")
    monkeypatch.setenv("IDENTITY_HEADER", "offline-identity-header")
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("MSI_ENDPOINT", raising=False)
    requests = []
    created = False

    class Response(AsyncHttpResponse):
        def __init__(self, request, status, payload):
            super().__init__(request, None)
            self.status_code = status
            self.headers = {"Content-Type": "application/json"}
            self.content_type = "application/json"
            self.reason = "OK" if status == 200 else "Not Found"
            self.payload = json.dumps(payload).encode()

        def body(self):
            return self.payload

        async def load_body(self):
            pass

    class Transport(AsyncHttpTransport):
        async def open(self):
            pass

        async def close(self):
            pass

        async def __aexit__(self, *args):
            await self.close()

        async def send(self, request, **kwargs):
            nonlocal created
            requests.append(request)
            url = urlparse(request.url)
            if url.hostname == "hosted-token-service.test":
                assert request.headers["X-IDENTITY-HEADER"] == "offline-identity-header"
                query = parse_qs(url.query)
                assert query["resource"] == ["https://management.azure.com"]
                assert query["api-version"] == ["2019-08-01"]
                assert "client_id" not in query
                return Response(request, 200, {
                    "access_token": "offline-agent-token", "expires_on": "4102444800",
                    "resource": "https://management.azure.com", "token_type": "Bearer",
                })
            assert url.hostname == "management.azure.com"
            assert request.headers["Authorization"] == "Bearer offline-agent-token"
            assert url.path == (
                f"/subscriptions/{SETTINGS.azure_subscription_id}/resourcegroups/mea-agent-demo"
            )
            if request.method == "PUT":
                body = json.loads(request.body)
                assert body["location"] == "eastus"
                created = True
            if not created:
                return Response(request, 404, {"error": {"code": "ResourceGroupNotFound"}})
            return Response(request, 200, {
                "id": group().id, "name": "mea-agent-demo", "location": "eastus",
                "properties": {"provisioningState": "Succeeded"},
            })

    real_client = azure_tools.ResourceManagementClient
    monkeypatch.setattr(
        azure_tools, "ResourceManagementClient",
        lambda credential, subscription: real_client(
            credential, subscription, transport=Transport(), retry_total=0,
        ),
    )
    tool = AzureResourceGroupTools(
        SETTINGS, lambda: ManagedIdentityCredential(transport=Transport(), retry_total=0),
    )
    result = asyncio.run(tool.deploy_resource_group("mea-agent-demo"))
    assert result["outcome"] == "created_and_verified"
    assert result["id"] == group().id
    assert [request.method for request in requests] == ["GET", "GET", "PUT", "GET"]
