# Sandbox-hosted agent with an Agent 365 agent identity

This sample extends [`sandbox-hosted-agent`](../sandbox-hosted-agent) so that the agent no
longer borrows the developer's credentials. Instead it gets its **own Microsoft Entra agent
identity**, the identity foundation that
[Microsoft Agent 365](https://learn.microsoft.com/microsoft-agent-365/developer/agent-365-sdk)
uses to govern, audit, and authorize agents.

The sample covers the Agent 365 **Register** stage end to end and then runs the agent with
that identity:

1. **Create** an agent identity blueprint, its blueprint principal, a credential, and one or
   more agent identities (`app/manage_identity.py`).
2. **Manage** agent identities: list, show, disable, re-enable, and delete them, or delete
   the whole blueprint.
3. **Run** the Agent Framework process inside an Azure Container Apps sandbox. It calls
   Microsoft Foundry with a token issued **to the agent identity**, and uses the Agent 365
   SDK (`microsoft-agents-a365-runtime`) to resolve the agent identity and parent blueprint
   from that token.

## How the pieces fit

| Concern | Implementation |
| --- | --- |
| Blueprint and agent identity provisioning | [Entra Agent ID Microsoft Graph APIs](https://learn.microsoft.com/entra/agent-id/create-blueprint) (`app/graph.py`). The Agent 365 SDK doesn't provision identities. The [Agent 365 CLI](https://learn.microsoft.com/microsoft-agent-365/developer/reference/cli/setup) wraps the same APIs. |
| Agent identity tokens | [Autonomous agent token flow](https://learn.microsoft.com/entra/agent-id/autonomous-agent-authentication-authorization-flow): the blueprint requests an exchange token with `fmi_path=<agent identity>`, which becomes the agent identity's client assertion (`app/agent_token.py`, MSAL). |
| Agent identity resolution | Agent 365 SDK `Utility.get_app_id_from_token`, `Utility.get_agent_id_from_token` (blueprint from `xms_par_app_azp`), and `Utility.get_user_agent_header` (`app/sandbox_agent.py`, `identity whoami`). |
| Agent runtime | Agent Framework with `FoundryChatClient`, executed in an ephemeral sandbox (`app/host.py`). |

```text
developer ──device code──▶ Graph: create blueprint / agent identity, enable / disable / delete
launcher  ──blueprint credential──▶ Entra: exchange token (fmi_path) ──▶ agent identity token (ai.azure.com)
launcher  ──upload token──▶ sandbox: Agent 365 SDK resolves identity ──▶ Foundry model call as the agent identity
```

## Prerequisites

- Deploy the environment in [`infra/README.md`](../../infra/README.md) with
  `deploySandboxGroup=true`.
- Sign in with `az login`. Your identity needs **Container Apps SandboxGroup Data Owner** on
  the sandbox group, and permission to create role assignments on the Foundry account.
- An Entra role that can create agent identity blueprints. If the tenant setting **Users can
  create agent blueprints** is off, you need **Agent ID Developer** or **Agent ID
  Administrator**. Adding a client secret to a blueprint requires **Agent ID Administrator**.
  Blueprint owners can manage the blueprint's agent identities without extra roles.
- Python 3.11 or newer locally (required by the Agent 365 SDK).

The management CLI signs you in with the device code flow using the Microsoft Graph
PowerShell public client (`14d82eec-204b-4c2f-b7e8-296a70dab67e`), and requests only the
delegated Agent ID scopes needed for each command, such as `AgentIdentityBlueprint.Create` or
`AgentIdentity.EnableDisable.All`. Set `GRAPH_CLIENT_ID` to use your own public client
registration instead. The token cache is persisted under the name
`agent365-identity-sample`. On machines without a secret store, it falls back to an
unencrypted file, so use this only on development machines.

## Setup

```bash
cd samples/agent365-identity-agent
pip install -r requirements.txt

cp .env.example .env
# Fill in AZURE_TENANT_ID and the infra deployment outputs, then export them.
export $(grep -v '^#' .env | xargs)
```

### 1. Create the agent identity blueprint

```bash
python -m app.manage_identity blueprint create --name "Contoso sandbox agent blueprint"
# -> export AGENT_BLUEPRINT_APP_ID=<blueprintAppId>
```

You become the blueprint's owner and, unless you pass `--sponsor-id`, its sponsor.

### 2. Give the blueprint a credential

For local development, add a short-lived client secret:

```bash
python -m app.manage_identity blueprint add-secret --days 30
# -> export AGENT_BLUEPRINT_CLIENT_SECRET=<secret printed once>
```

On Azure compute, trust a managed identity instead and leave the secret empty:

```bash
python -m app.manage_identity blueprint add-managed-identity --principal-id <managed-identity-object-id>
# Set AGENT_BLUEPRINT_MANAGED_IDENTITY_CLIENT_ID for a user-assigned identity.
```

### 3. Create the agent identity

```bash
python -m app.manage_identity identity create --name "Contoso sandbox agent"
# -> export AGENT_IDENTITY_ID=<agentIdentityId> AGENT_IDENTITY_CLIENT_ID=<agentIdentityClientId>

python -m app.manage_identity identity whoami
```

`whoami` performs the full blueprint-to-agent-identity token exchange and prints the agent
identity and blueprint IDs that the Agent 365 SDK resolves from the token. It never prints the
token.

### 4. Authorize the agent identity for Foundry

The agent identity is a service principal, so grant it data-plane access with Azure RBAC:

```bash
FOUNDRY_ID=$(az cognitiveservices account list -g "$AZURE_RESOURCE_GROUP" --query "[0].id" -o tsv)
az role assignment create \
  --assignee-object-id "$AGENT_IDENTITY_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Azure AI User" \
  --scope "$FOUNDRY_ID"
```

Role assignments can take a few minutes to propagate.

## Run

```bash
python -m app.run_agent "Why should an AI agent have its own identity?"
```

Example output:

```text
Agent identity: 9f6c...   # appid of the agent identity
Blueprint:      3b1e...   # xms_par_app_azp, the parent blueprint
User-Agent:     Agent365SDK/2.0.0 (Linux; Python 3.14.0; AgentFramework)

An agent identity makes every action attributable, auditable, and revocable ...
```

The launcher acquires the agent identity token **before** creating a sandbox, so a disabled
or deleted identity fails fast without provisioning compute.

## Manage agent identities

| Command | What it does | Delegated scope |
| --- | --- | --- |
| `identity list [--all]` | List agent identities of the blueprint, or of every blueprint. | `AgentIdentity.Read.All` |
| `identity show [--id ID]` | Show one agent identity. | `AgentIdentity.Read.All` |
| `identity disable [--id ID]` | Set `accountEnabled=false`. New token requests fail, which is the agent's kill switch. | `AgentIdentity.EnableDisable.All` |
| `identity enable [--id ID]` | Re-enable a disabled agent identity. | `AgentIdentity.EnableDisable.All` |
| `identity delete [--id ID] --yes` | Delete the agent identity. | `AgentIdentity.DeleteRestore.All` |
| `blueprint show` | Show the configured blueprint. | `AgentIdentityBlueprint.Read.All` |
| `blueprint delete --yes` | Delete the blueprint. Entra also deletes all of its agent identities. | `AgentIdentityBlueprint.DeleteRestore.All` |

Try the kill switch:

```bash
python -m app.manage_identity identity disable
python -m app.run_agent "Still there?"   # fails: the agent identity can't get a token
python -m app.manage_identity identity enable
```

Changes can take a short time to take effect, and tokens that were already issued stay valid
until they expire.

### Manage identities as the blueprint (automation)

`identity create`, `enable`, `disable`, and `delete` also accept `--auth blueprint`. Graph
is then called app-only with the blueprint's own credential. That is the pattern a
provisioning service uses to create one agent identity per agent instance without a signed-in
user. App-only creation needs an explicit sponsor:

```bash
python -m app.manage_identity identity create --name "Agent instance 42" --auth blueprint --sponsor-id <user-object-id>
```

If Graph returns 403, the blueprint principal also needs the corresponding application
permission (for example `AgentIdentity.CreateAsManager`).

## Agent 365 registry

Identities created through the Graph APIs don't automatically appear in the Agent 365
registry in the Microsoft 365 admin center. To make the blueprint discoverable and governable
there, register it with `a365 setup all --agent-registration-only`, or call the
[Agent Registry API](https://learn.microsoft.com/microsoft-365/copilot/extensibility/api/admin-settings/agent-registration/overview).

## Trust boundary

The trust boundary is the same as in [`sandbox-hosted-agent`](../sandbox-hosted-agent#trust-boundary),
but the token in the sandbox now belongs to the agent identity, not to you. It's
scoped to Foundry (`https://ai.azure.com/.default`), short-lived, and limited to the
permissions you granted the agent identity. Still, **don't run model-generated or
user-supplied code in the same sandbox**. The blueprint credential (secret or managed identity)
stays on the launcher and never enters the sandbox.

The Agent 365 SDK identity helpers decode tokens **without signature verification**. The
sandbox uses them for diagnostics and fail-fast misconfiguration checks, not authorization.

## Files

| File | Purpose |
| --- | --- |
| `app/manage_identity.py` | CLI to create and manage the blueprint and agent identities. |
| `app/graph.py` | Microsoft Graph client for Entra Agent ID blueprints and agent identities. |
| `app/agent_token.py` | Blueprint to agent identity token exchange (MSAL, `fmi_path`). |
| `app/host.py` | Host-side sandbox provisioning, agent identity token transfer, execution, and cleanup. |
| `app/sandbox_agent.py` | Agent Framework program that runs inside the sandbox and resolves its identity with the Agent 365 SDK. |
| `app/run_agent.py` | Command-line entry point for running the agent. |
| `requirements.txt` | Dependencies for the launcher and management CLI. |
| `requirements-sandbox.txt` | Dependencies installed inside the sandbox. |
| `tests/` | Offline tests using fake Graph, MSAL, and sandbox clients. |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests require no Azure resources, tenant, or credentials.

## Clean up

```bash
az role assignment delete --assignee "$AGENT_IDENTITY_ID" --scope "$FOUNDRY_ID"
python -m app.manage_identity blueprint delete --yes   # also deletes its agent identities
```
