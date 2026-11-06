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
| Agent identity tokens | Inside the sandbox, managed-identity federation authenticates the blueprint and requests an exchange token with `fmi_path=<agent identity>`. User-assigned identities use Microsoft 365 Agents SDK `MsalAuth.get_agentic_application_token`; system-assigned identities use the shared Azure Identity/MSAL provider in `app/agent_token.py`. MSAL exchanges the blueprint token for a Foundry token as the agent identity (`app/sandbox_agent.py`). |
| Agent identity resolution | Agent 365 SDK `Utility.get_app_id_from_token`, `Utility.get_agent_id_from_token` (blueprint from `xms_par_app_azp`), and `Utility.get_user_agent_header` (`app/sandbox_agent.py`, `identity whoami`). |
| Agent runtime | Agent Framework with `FoundryChatClient`, executed in an ephemeral sandbox (`app/host.py`). |

```text
developer ──device code──▶ Graph: create blueprint / agent identity, enable / disable / delete
launcher  ──upload code + non-secret configuration──▶ sandbox
sandbox   ──managed identity federation──▶ blueprint exchange (fmi_path) ──▶ agent identity token (ai.azure.com)
sandbox   ──Agent 365 SDK resolves identity──▶ Foundry model call as the agent identity
```

The Agent 365 runtime SDK provides identity helpers, not a token-acquisition client.
Authentication uses the companion Microsoft 365 Agents authentication SDK and MSAL,
following the [Agent 365 SDK service-to-service token pattern](https://learn.microsoft.com/microsoft-agent-365/developer/observability).
The SDK's `FederatedCredentials` mode requires a user-assigned identity client ID.
For system-assigned federation, the sample uses its shared Azure Identity/MSAL provider
instead; both paths retain the Agent 365 SDK identity diagnostics.

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
- A system-assigned or user-assigned managed identity attached to the sandbox group.
  Leave `AGENT_BLUEPRINT_MANAGED_IDENTITY_CLIENT_ID` empty for the system-assigned identity;
  for a user-assigned identity, set its **client ID**, not its object/principal ID.
  The sandbox runtime must be able to acquire
  managed identity tokens for `api://AzureADTokenExchange`; attaching a group identity alone
  does not verify that capability.

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
# Only source a trusted local file. Quote values containing spaces or shell operators.
set -a
source .env
set +a
```

### 1. Create the agent identity blueprint

```bash
python -m app.manage_identity blueprint create --name "Contoso sandbox agent blueprint"
# -> export AGENT_BLUEPRINT_APP_ID=<blueprintAppId>
```

You become the blueprint's owner and, unless you pass `--sponsor-id`, its sponsor.

### 2. Give the blueprint a credential

Trust the sandbox group's managed identity (system-assigned or user-assigned):

```bash
python -m app.manage_identity blueprint add-managed-identity --principal-id <managed-identity-object-id>
# System-assigned:
export AGENT_BLUEPRINT_MANAGED_IDENTITY_CLIENT_ID=
# Or, for a user-assigned identity:
# export AGENT_BLUEPRINT_MANAGED_IDENTITY_CLIENT_ID=<managed-identity-client-id>
```

The federated credential uses the managed identity's **object/principal ID**; runtime
configuration uses its **client ID**. The launcher passes only non-secret identity IDs to
the sandbox. It never uses a blueprint secret to run the agent.

If the Agents SDK reports `invalid_scope` with `error_description: 'None, None'`, this can
mask a managed identity endpoint error rather than an invalid audience. Check the identity
selection first: a system-assigned identity must not be selected by its principal ID.
For a user-assigned identity, verify the configured client ID belongs to an identity
actually attached to the sandbox group.

For local management commands such as `identity whoami`, you can optionally add a
short-lived development secret:

```bash
python -m app.manage_identity blueprint add-secret --days 30
# -> export AGENT_BLUEPRINT_CLIENT_SECRET=<secret printed once>
```

On Azure compute with access to the trusted managed identity, management commands can also
use federation instead of a secret.

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
  --role "Foundry User" \
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

The sandbox acquires its agent identity token at runtime and reacquires tokens through a
refreshable credential backed by MSAL's in-memory cache. A disabled or deleted identity
fails inside the sandbox; the launcher reports the failure and deletes the sandbox.
`identity whoami` runs locally, so it needs a credential available on the local machine,
even when the sandbox itself uses managed identity.

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

The repository's devcontainer installs the Agent 365 CLI (`a365`) automatically.
For an existing Codespace, rebuild the container and verify with `a365 --help`.
See [CLI installation and update instructions](../../README.md#agent-365-cli-in-codespaces).

Identities created through the Graph APIs don't automatically appear in the Agent 365
registry in the Microsoft 365 admin center. To make the blueprint discoverable and governable
there, register the existing agent identity with `a365 setup all --agent-registration-only`,
or call the
[Agent Registry API](https://learn.microsoft.com/microsoft-365/copilot/extensibility/api/admin-settings/agent-registration/overview).
Entra identity provisioning and Agent 365 registration are separate steps.

### Set up with the Agent 365 skill

Ask Copilot: **"Use the a365-setup skill to register
samples/agent365-identity-agent with Agent 365, reusing its existing blueprint and agent
identity."** Confirm these choices:

- **Stack / language:** Microsoft Agent Framework / Python.
- **Agent type:** Agent (Non AI Teammate), without Teams or Copilot integration.
- **Capabilities:** Register. Observability is an optional, separate instrumentation step.
- **Authentication:** Service-to-service (S2S). The sandbox acts as the agent identity,
  not on behalf of a signed-in user.
- **Existing identity:** Reuse `AGENT_BLUEPRINT_APP_ID` and `AGENT_IDENTITY_ID` from
  your local `.env`, even if no `a365.config.json` exists yet.

Do not select AI Teammate for this sample unless you intend to change its hosting and
identity model. WorkIQ requires delegated user authentication and is not part of this
S2S setup. The skill delegates registration to `make-a365-agent` after validating
prerequisites. For this already-provisioned sample, use the registration-only command
below rather than provisioning a replacement blueprint.

### 1. Authenticate and validate prerequisites

Run from this sample directory with the environment variables from [Setup](#setup)
exported. Keep your existing `.env`; do not copy the example over it.

```bash
dotnet --version
pwsh --version
dotnet tool list --global
az login --allow-no-subscriptions --tenant "$AZURE_TENANT_ID" --use-device-code
az account show --query '{tenantId:tenantId, subscription:name}' -o json
```

Confirm the tenant matches `AZURE_TENANT_ID`. Signing into Azure through the VS Code
extension does **not** sign the Azure CLI in. Omit `--use-device-code` when browser login
is available. A subscription is not needed for registry-only setup; the sandbox and
Foundry runtime still require the Azure resources and permissions described above.

The CLI needs .NET 8+, PowerShell 7+, and the Az PowerShell module. If the module is
missing, install it with:

```bash
pwsh -NoProfile -Command 'Install-Module -Name Az -AllowClobber -Scope CurrentUser -Force -Repository PSGallery'
```

Validate the **Agent 365 CLI** client application's actual authorization with the CLI.
Registration requires a delegated token containing `AgentRegistration.ReadWrite.All`.
The CLI's interactive delegated authentication is separate from the sandbox's S2S
authentication. Do not substitute the sample's `GRAPH_CLIENT_ID`, blueprint ID, or agent
identity ID for the CLI client application ID.

For a tenant-owned client named **Agent 365 CLI**, find its application ID with:

```bash
az ad app list --display-name "Agent 365 CLI" \
  --query '[].{name:displayName, clientAppId:appId}' -o json
```

An empty result does not mean the CLI application is missing. CLI 2.0.1 supports the
Microsoft-managed Agent 365 CLI enterprise application
(client ID `f54280f4-395e-4ea8-9e48-bf2d4952aa14`). Find it under Entra **Enterprise
applications**, with the application-type filter set to include Microsoft applications,
not under tenant-owned **App registrations**.

After preparing the local configuration in step 2, run:

```bash
a365 setup requirements --category Authentication
```

Complete the CLI's device-code sign-in when prompted. For the Microsoft-managed app,
the check validates the scopes on acquired delegated tokens, including the registration
scope. An empty Enterprise application Permissions page or an empty
`oauth2PermissionGrants` result alone does **not** prove missing authorization:
first-party preauthorization can provide access without those tenant-local grants.
The portal may also report that you cannot view preauthorized permissions. Do not
modify Microsoft's application, create a duplicate app, or retry a generic admin-consent
URL solely because the portal shows no permissions. Use the actual CLI check result.

For a tenant-owned custom client, follow the
[custom client app registration guide](https://learn.microsoft.com/microsoft-agent-365/developer/custom-client-app-registration)
to configure permissions and administrator consent. If the managed-app CLI check fails,
resolve its specific authentication or missing-scope error with your administrator.
Creating blueprints requires **Agent ID Developer** or a higher applicable role;
registration-only setup does not recreate blueprints or grant Foundry permissions.
Resolve missing permissions or consent before continuing.

### 2. Connect the CLI to the existing identities

Create these two **local** files in this sample directory, replacing the placeholders.
If either file already exists, preserve its contents and merge the relevant fields
instead of overwriting it, especially an existing `agentRegistrationId`.
The CLI does not load the sample's `.env` automatically.

`a365.config.json`:

```json
{
  "tenantId": "<AZURE_TENANT_ID>",
  "clientAppId": "<validated Agent 365 CLI application client ID>",
  "agentIdentityDisplayName": "<existing agent identity display name>",
  "agentDescription": "Sandbox-hosted Agent Framework agent with its own Entra identity",
  "aiTeammate": false,
  "useBlueprint": true,
  "authMode": "s2s"
}
```

`a365.generated.config.json`:

```json
{
  "agentBlueprintId": "<AGENT_BLUEPRINT_APP_ID>",
  "agenticAppId": "<AGENT_IDENTITY_ID>"
}
```

For CLI 2.0.1, `agentBlueprintId` is the blueprint's **application/client ID**, while
`agenticAppId` is the agent identity's **service-principal object ID**, despite its name.
Use `AGENT_IDENTITY_ID`, not an unrelated application's client ID. These files connect the
CLI to existing resources; they do not prove registration has succeeded.
No blueprint secret is needed for this registration-only path.

### 3. Preview, register, and verify

After the CLI Authentication requirement passes:

```bash
a365 --version
a365 setup all --agent-registration-only --authmode s2s --dry-run
```

Check that the preview reuses the configured identity and skips blueprint creation and
permission grants. Stop if it proposes a new identity or shows the wrong IDs. Do not add
`--agent-name`: the explicit local configuration above is the source of the existing IDs.
After reviewing the preview, apply:

```bash
a365 setup all --agent-registration-only --authmode s2s
```

Check the full setup summary for successful **Agent Registration**, not just a successful
blueprint or identity lookup. The generated configuration should now contain an
`agentRegistrationId`. Verify the registration in the tenant's
[Microsoft 365 admin center](https://admin.cloud.microsoft/) under **Agents**, allowing
for propagation time. If setup reports missing consent, follow its administrator handoff
and retry the registration-only command; do not delete the existing blueprint.
If the identity was previously registered from another machine, recover that registration's
CLI state or check with your administrator before applying to avoid a duplicate registration.

Keep the generated configuration for retries: its registration ID enables reuse instead
of duplicate registrations. Both CLI configuration files are ignored by Git because
later setup operations can store credentials there.

Registration alone does not enable activity tracing or change the sandbox's managed-identity
federation or Foundry RBAC. Optional activity tracing is wired as described below.
Installing the runtime SDK or registering the identity alone does not emit telemetry.

## Agent 365 Activity telemetry

The sample includes opt-in instrumentation using `microsoft-opentelemetry` 1.6+.
Configure these values in your local `.env`, then export it as described in [Setup](#setup):

```dotenv
ENABLE_A365_OBSERVABILITY_EXPORTER=true
A365_CAPTURE_CONTENT=false
A365_SPONSOR_ID=<actual blueprint sponsor user object ID>
A365_SPONSOR_NAME="<actual sponsor display name>"
A365_SPONSOR_EMAIL=<actual sponsor email>
OTEL_LOG_LEVEL=INFO
A365_OBSERVABILITY_LOG_LEVEL="info|warn|error"
```

Look up the actual blueprint sponsor in Entra, or query it read-only:

```bash
az rest --method GET \
  --url "https://graph.microsoft.com/beta/applications/${AGENT_BLUEPRINT_APP_ID}/microsoft.graph.agentIdentityBlueprint/sponsors"
```

Use the sponsor's real user object ID, name, and email, not the blueprint ID. The
`A365_SPONSOR_*` settings attribute autonomous activity to its sponsor; they do not
impersonate a signed-in user and do not alter `AGENT_SPONSOR_ID` used by management commands.
These identity details are included in exported telemetry.

Run one request:

```bash
python -m app.run_agent "Why should an AI agent have its own identity?"
```

The launcher uploads the tracing module and non-secret settings along with the agent.
Inside the sandbox, the runtime:

- Acquires an **app-only token for the agent identity**, reusing the existing managed
  identity / blueprint FMI exchange with the Observability API scope
  `api://9b975845-388f-4429-889e-eab1ef63949c/.default`. The Foundry token is not reused
  for telemetry, and no secret or developer token is uploaded.
- Initializes `use_microsoft_opentelemetry` before importing Agent Framework, with both
  exporter activation flags and `a365_use_s2s_endpoint=True`. Offline disk spooling is
  disabled because the sandbox is ephemeral.
- Applies outer baggage carrying the agent identity and tenant, then manual
  `invoke_agent` and child `chat` scopes, sponsor attribution, model/token usage, and
  output messages. The Agent Framework agent ID matches the runtime identity.
  Distro auto-instrumentation and Agent Framework's separate native instrumentation
  are disabled to avoid duplicate spans.
- Refreshes the export token before expiry and flushes/shuts down tracing before the
  sandbox is deleted, including when the model call fails.

This agent currently has **no tool calls**, so it does not fabricate `execute_tool`
spans. If you add tools, instrument their real executions with `ExecuteToolScope`.
Tool-enabled agents need that instrumentation for complete Activity/store validation.
This CLI runtime has no Teams adapter; baggage is constructed directly rather than
through hosting middleware.

By default, tracing is disabled and message content is redacted. Set `A365_CAPTURE_CONTENT=true`
only when prompts and answers are approved for storage in telemetry. Exporter errors and
token failures are surfaced; sandbox diagnostics are forwarded to the launcher's stderr.
A successful agent answer alone does not prove telemetry was ingested: check exporter
diagnostics for a successful HTTP export. `force_flush` only confirms that queued spans
were processed, not that the service accepted them.
In distro 1.6, the explicit `HTTP 200 success` export diagnostic is logged at DEBUG:
temporarily set `OTEL_LOG_LEVEL=DEBUG` and
`A365_OBSERVABILITY_LOG_LEVEL="debug|info|warn|error"` when verifying ingestion, then
restore the normal levels.

Registered blueprint agent instances use the S2S route without an additional
Observability API delegated-consent step, subject to service policy. If export returns
403, check the exact response and verify the existing agent's registration before
changing permissions. Allow indexing time after a successful export before checking
Agent 365 Activity / Defender; filter by the **agent identity**, not the blueprint.
Set `ENABLE_A365_OBSERVABILITY_EXPORTER=false` to restore the original untraced run.

## Trust boundary

The trust boundary is the same as in [`sandbox-hosted-agent`](../sandbox-hosted-agent#trust-boundary),
but the token in the sandbox now belongs to the agent identity, not to you. It's
scoped to Foundry (`https://ai.azure.com/.default`), short-lived, and limited to the
permissions you granted the agent identity. Still, **don't run model-generated or
user-supplied code in the same sandbox**. No token file or blueprint secret is uploaded.
Instead, sandbox code can authenticate the blueprint through its trusted managed identity,
which is a broader capability than holding a single Foundry token. Code with access to that
identity can request tokens for other agent identities managed by the same blueprint,
subject to their permissions. Use separate blueprints and managed identities for different
trust boundaries; do not share this identity with untrusted sandboxes.

The Agent 365 SDK identity helpers decode tokens **without signature verification**. The
sandbox uses them for diagnostics and fail-fast misconfiguration checks, not authorization.

## Files

| File | Purpose |
| --- | --- |
| `app/manage_identity.py` | CLI to create and manage the blueprint and agent identities. |
| `app/graph.py` | Microsoft Graph client for Entra Agent ID blueprints and agent identities. |
| `app/agent_token.py` | Shared blueprint-to-agent token exchange (MSAL, `fmi_path`), used by management commands and system-assigned sandbox federation. |
| `app/host.py` | Host-side sandbox provisioning, non-secret configuration transfer, execution, and cleanup. |
| `app/sandbox_agent.py` | Sandbox-local managed identity federation, refreshable agent token credential, and Agent Framework execution with Agent 365 identity diagnostics. |
| `app/observability.py` | Optional S2S export token refresh, sponsor/identity baggage, invocation/inference scopes, and shutdown flushing inside the sandbox. |
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
