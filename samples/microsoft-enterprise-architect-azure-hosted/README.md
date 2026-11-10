# Microsoft Enterprise Architect Azure Hosted

A separate sample based on
[`microsoft-enterprise-architect-hosted`](../microsoft-enterprise-architect-hosted).
It keeps Microsoft Learn MCP, the full Work IQ MCP catalog, the request-scoped
Responses host, source ZIP deployment, and native Teams publishing. It adds
Python tools that use **the hosted agent's own Entra identity** to access Azure
Resource Manager (ARM) and deploy an **empty resource group**.
The original sample and its deployment are unchanged.

```text
CLI / Foundry playground / published Teams personal chat
                          |
             Foundry hosted Responses server
                          |
             Agent Framework + FoundryChatClient
                /                  \
    Microsoft Learn + Work IQ      Local Python tools -> ARM
    delegated M365 user access     application-only agent identity
```

Default deployment: `mea-azure-hosted-agent`. Display name for publishing:
**Microsoft Enterprise Architect Azure Hosted**.

## Identity and boundaries

Foundry provisions an agent instance identity separately from its blueprint and
the project's managed identity. The runtime's token service exposes that instance
identity through `ManagedIdentityCredential`. ARM requests use
`https://management.azure.com/.default`; Azure RBAC and Azure Policy decide
whether they succeed. No user token, client secret, blueprint credential,
subscription credential, or developer CLI identity is shipped in the ZIP.

The host uses explicit `ManagedIdentityCredential` for model calls and the async
equivalent for ARM. Each Azure tool call closes its own credential and ARM client.
**There is no developer-credential fallback in the runtime.** Running `main.py`
outside Foundry without its token service will not exercise the agent identity.
Deployment, identity lookup, invocation, and agent deletion use the operator's
`DefaultAzureCredential` locally; that credential is not passed to ARM tools.
The SDK's first-party caller-context headers are still forwarded to Foundry.
Work IQ retains its separate delegated Microsoft 365 connection and consent.

See the official [agent identity concepts](https://learn.microsoft.com/azure/foundry/agents/concepts/agent-identity)
and [hosted-agent token service reference](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-token-service).

The local tools expose:

| Tool | Behavior |
| --- | --- |
| `azure_deployment_context` | Return the configured subscription, prefix, region, and authentication mode. No tokens. |
| `list_resource_groups` | List groups, returning only names matching the configured prefix. |
| `get_resource_group` | Read one prefix-matching group's ARM metadata. |
| `deploy_resource_group` | Create an empty, sample-tagged group in the fixed region and read it back; return an existing same-region group unchanged. Reject a region conflict. |

The subscription and region are **operator configuration, not model arguments**.
Names must start with the configured prefix, have a suffix, and contain at most
90 ASCII letters, digits, underscores, or hyphens. No arbitrary ARM URL, shell,
workload deployment, deletion, or role-assignment tool is exposed. Authentication,
RBAC, policy, and verification failures propagate as tool errors, not success.

## Prerequisites

- The [base sample's prerequisites and Work IQ connection setup](../microsoft-enterprise-architect-hosted/README.md#prerequisites-and-connections),
  including a Foundry project/model and a disposable M365 tenant with synthetic
  data. Work IQ remains required; no separate toolbox or SharePoint MCP is used.
- Python 3.10+ locally; source deployment uses Foundry's `python_3_14` runtime.
- A **disposable Azure subscription** in the agent identity's tenant. The target
  subscription may differ from the Foundry project's subscription.
- An administrator authorized to create a custom Azure role and assign it at
  target subscription scope. The deployer does not grant itself or the agent
  any permissions.
- A valid Azure region allowed by subscription policy.

## Configure and deploy

```bash
cd samples/microsoft-enterprise-architect-azure-hosted
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit the endpoint/model, Work IQ connection, target subscription, prefix, region.
set -a
source .env
set +a
az login
python -m app.deploy
```

Environment files are not loaded automatically. Source only trusted shell values;
no secrets or tokens belong in `.env`.

| Variable | Purpose |
| --- | --- |
| `FOUNDRY_PROJECT_ENDPOINT` | Foundry project endpoint. Required. |
| `FOUNDRY_MODEL_DEPLOYMENT` | Model deployment; falls back to `AZURE_AI_MODEL_DEPLOYMENT_NAME`, then `gpt-5.3-codex-2`. |
| `WORKIQ_CONNECTION_NAME` | Existing Work IQ MCP project connection. Required for deployment. |
| `WORKIQ_CONNECTION_ID` | Resolved by deployment and supplied to the runtime. |
| `AZURE_SUBSCRIPTION_ID` | Target subscription's canonical lowercase UUID. Required for deployment/runtime. |
| `AZURE_RESOURCE_GROUP_PREFIX` | Default `mea-agent-`; 2-40 lowercase letters/digits/hyphens, ending in `-`. |
| `AZURE_RESOURCE_GROUP_LOCATION` | Default `eastus`; use the Azure region identifier, not its display name. |

The ZIP allowlist contains only `main.py`, `requirements.txt`,
`app/__init__.py`, `app/agent.py`, `app/config.py`, `app/host.py`, and
`app/azure_tools.py`. No `.env`, tests, RBAC files, or operator scripts are uploaded.
Deployment validates configuration and the Work IQ connection, creates a new
hosted Responses 2.0.0 version, waits for `active`, and then switches endpoint
traffic. Existing published protocols and authorization schemes are preserved.
Failures do not switch routing; temporary ZIPs are removed.

## Grant the agent permission once

Deploy first so Foundry creates the agent identity, then run as the authorized
administrator. `app.identity` reads `instance_identity.principal_id` from the
named agent, **not the blueprint ID, client ID, or project identity**.

```bash
AGENT_PRINCIPAL_ID=$(python -m app.identity)

# Render the custom-role scope without modifying the checked-in template.
python - <<'PY'
import json
import os
from pathlib import Path

role = json.loads(Path("resource-group-role.json").read_text())
role["AssignableScopes"] = [f"/subscriptions/{os.environ['AZURE_SUBSCRIPTION_ID']}"]
Path("resource-group-role.local.json").write_text(json.dumps(role, indent=2))
PY

ROLE_ID=$(az role definition create \
  --subscription "$AZURE_SUBSCRIPTION_ID" \
  --role-definition resource-group-role.local.json --query name -o tsv)
ROLE_ASSIGNMENT_ID=$(az role assignment create \
  --assignee-object-id "$AGENT_PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "$ROLE_ID" \
  --scope "/subscriptions/$AZURE_SUBSCRIPTION_ID" --query id -o tsv)
```

Record these non-secret IDs for cleanup. If the role already exists, reuse its
ID rather than creating it again. Allow time for RBAC propagation. No redeployment
is needed for a role grant. Do not assign Owner, Contributor, or role-management
permissions to make this demonstration work.

The [custom role](resource-group-role.json) contains only
`Microsoft.Resources/subscriptions/resourceGroups/read` and
`Microsoft.Resources/subscriptions/resourceGroups/write`. Subscription scope is
necessary to create groups that do not yet exist. It grants **read/write metadata
access to all resource groups in that subscription**, not just the prefix; it
does not grant deployment of resources inside them or group deletion. The list
operation reads the subscription's group list before filtering locally.
The prefix/region checks constrain these Python tools, **not the identity's RBAC
rights**. Use a disposable subscription, restrict callers of the agent endpoint,
and use Azure Policy for enforceable naming/location/tag restrictions.

## Invoke and verify

```bash
python -m app.invoke "Show your Azure deployment context and list your workshop resource groups."
python -m app.invoke "Deploy a new empty resource group named mea-agent-demo-001 in your configured subscription and region. Return its verified ARM ID."
python -m app.invoke "Read the resource group mea-agent-demo-001 and report its location and tags."
# Retry: should report existing_unchanged, not update tags or recreate anything.
python -m app.invoke "Deploy the empty resource group mea-agent-demo-001 again."
```

Verify independently as an authorized operator:

```bash
az group show --subscription "$AZURE_SUBSCRIPTION_ID" \
  --name mea-agent-demo-001 --query '{id:id,location:location,state:properties.provisioningState,tags:tags}'
```

Check the subscription's Azure Activity Log for the resource-group write and
confirm its caller/object ID is `AGENT_PRINCIPAL_ID`, **not the CLI user or project
identity**. Test a new group before granting RBAC and confirm denial, then grant
the role and retry. Also test wrong-prefix requests, policy-denied locations,
same-region existing groups with custom tags, and groups in another region.
Actual tool traces and ARM/Activity Log evidence, not the model's prose, establish
which identity acted and whether deployment worked.

Use the base sample's [Microsoft 365 invocation exercises](../microsoft-enterprise-architect-hosted/README.md#invoke)
and [native Teams publishing guidance](../microsoft-enterprise-architect-hosted/README.md#workshop-safety-and-teams)
with this sample's agent name and display name. State in the published description
that it can create empty Azure resource groups as its own identity without
per-call approval prompts. Keep initial distribution private.
Use `--name custom-mea-azure` consistently on deploy, identity, invoke, and delete
to isolate another named agent; grant RBAC to that agent's own principal.

## Safety and limitations

Every authorized caller of this endpoint can potentially exercise the **same
application-only Azure privileges**. Microsoft 365 user consent does not constrain
those privileges. Instructions require explicit user deployment requests and
treat documents/tool output as untrusted, but this is **not a human-approval
system, DLP, or per-user Azure authorization**. Both MCP services retain full
catalogs and `require_approval="never"`, as in the base sample.

The resource-group preflight GET and ARM PUT are **not atomic create-only
enforcement**. ARM's create-or-update API can update a group created concurrently
between them, including its tags. Use unique workshop names and no concurrent
creators; this sample is not suitable where strict no-overwrite guarantees are
required. Existing same-region groups discovered by preflight are never written.
Read-back must show an ID, the configured region, and `Succeeded` before the
tool reports `created_and_verified`.

No Azure workloads are created, but hosted compute/model/M365 usage can incur
charges. Azure policy may require additional tags; failures are surfaced rather
than bypassed. Subscription and group names/tags are tool data sent to the model.
Do not use sensitive names or production resources. CLI `--debug` can expose
private model/tool content. Conversations follow Foundry's host-managed retention.

## Cleanup

Remove published Teams distribution, remove the recorded role assignment, and
delete **only the empty resource groups created by this exercise** as an operator.
The agent intentionally has no deletion tool or deletion role permission.

```bash
az role assignment delete --ids "$ROLE_ASSIGNMENT_ID"
# Check contents before approving deletion; this command deletes ALL group contents.
az group delete --subscription "$AZURE_SUBSCRIPTION_ID" --name mea-agent-demo-001
python -m app.delete
# Only if you created this custom role and no other assignments use it:
az role definition delete --subscription "$AZURE_SUBSCRIPTION_ID" --name "$ROLE_ID"
rm resource-group-role.local.json
```

`app.delete` removes this named agent and all versions/routing, not Azure groups,
role assignments, shared Foundry resources, Work IQ connections, or documents.
Recreating a deleted agent can create a new identity; resolve its principal again
and regrant RBAC rather than reusing the old principal ID.

## Offline checks

```bash
pip install -r requirements-dev.txt
pytest
```

Checks cover MCP/function tool wiring, caller-context forwarding through the real
Responses host, source packaging, deployment/routing, identity lookup, bounded ARM
tools, no-op existing groups, read-back, failure propagation, and client cleanup.
Mocks do **not** establish live identity provisioning, role/Policy enforcement,
Azure deployment success, M365 consent, or Teams functionality. Run the live
verification steps above before claiming those work.
