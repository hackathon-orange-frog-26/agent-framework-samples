# Microsoft Enterprise Architect Prompt

A separate, persistent **Foundry prompt agent** displayed in Teams as
**Microsoft Enterprise Architect Prompt**. It adapts the lifecycle and evidence-based
instructions from the [enterprise architect sample](../enterprise-architect-prompt-agent)
and reuses its fictional policy files. It does **not** modify that agent, depend
on its A2A deployment, or create a Foundry vector store.

**Work IQ MCP provides all Microsoft 365 tools**, including SharePoint access.
**Microsoft Learn MCP** verifies Azure guidance against official documentation.
There is no separate SharePoint MCP or web-search tool.

```text
CLI / Foundry playground / Teams personal chat
                    |
          Foundry prompt agent
                    |
         Microsoft Learn MCP + Work IQ MCP
                    |
    SharePoint / OneDrive / Mail / Teams / Calendar / Agents
```

Both MCP servers use `require_approval="never"` and omit `allowed_tools`.
Microsoft Learn uses the public `https://learn.microsoft.com/api/mcp` endpoint
without an authenticated connection. The full live Work IQ catalog is exposed.
The current
[Work IQ MCP tool reference](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)
documents:

| Tools | Purpose |
| --- | --- |
| `ask`, `retrieve` | Copilot questions and enterprise retrieval, including SharePoint/OneDrive grounding |
| `list_agents` | Discover available agents |
| `search_paths`, `get_schema` | Discover supported resource paths and operation schemas |
| `fetch`, `fetch_blob` | Read entities and binary content |
| `create_entity`, `update_entity`, `delete_entity` | Supported entity mutations |
| `do_action`, `call_function` | Supported actions and functions |

No client-side allowlist freezes or restricts that catalog. Tool availability
depends on the server and tenant; `retrieve` is public preview. The agent uses
live schemas rather than assuming that every Graph path or operation works.
Exposing a tool is not proof it can execute: Work IQ blocks mutations by
default through tenant policy, and source permissions and consent still apply.

**Behavior change:** authorized, explicitly requested writes and actions can
execute without a confirmation prompt. This is no longer a read-only or
approval-gated sample. Use only a disposable tenant and synthetic data.
The [facilitator guide](WORKSHOP.md) covers retrieval, requested changes, and
negative cases. There is no Azure execution tool.

## Prerequisites

- Python 3.10+, `az login`, a Foundry project, and a tool-capable model deployment
  supporting MCP. Set the actual deployment name; the default is `gpt-5.3-codex-2`.
- **Foundry User** on the project; **Foundry Project Manager** to create the connection.
- A disposable Microsoft 365 workshop tenant, two test users, and an administrator
  for Work IQ consent, policy, and Teams app distribution. Check current
  [Work IQ prerequisites](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq#prerequisites).
  Connector licensing and Work IQ API billing differ.
- This repository checkout, including the original sample's policy directory.
  No original agent needs to be running.

## Connect Work IQ once

Follow the [Foundry Work IQ MCP quickstart](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/foundry).
Use the **MCP** endpoint, not the older `work_iq_preview` A2A tool:

1. Have an Entra administrator provision Work IQ if needed, configure a
   single-tenant app, add **Work IQ > Delegated permissions >
   `WorkIQAgent.Ask`** (and optionally **`WorkIQ.Act`** as described below),
   and grant admin consent for the selected permissions. Store its client secret only in the
   Foundry connection, never in this sample.
2. In your Foundry project, open **Tools > Connect a tool > Catalog**, select
   **Work IQ MCP**, and create `workshop-workiq-mcp` targeting
   `https://workiq.svc.cloud.microsoft/mcp`.
3. Configure delegated OAuth using the app's client ID and secret, tenant-specific
   authorization/token URLs, and the **exact Scopes value below**. Copy Foundry's generated
   redirect URI into the app's **Web** redirect URIs.
4. Inspect the live catalog against the tool reference above. Verify SharePoint
   retrieval through Work IQ, not an application-specific SharePoint server.
5. Test sign-in/consent using each participant's **own** identity. Do not share
   the facilitator's authorized session or use application-only access.
   Azure CLI sign-in authorizes Foundry calls; it does not by itself complete
   Work IQ OAuth consent.
6. For requested mutation exercises, have the administrator configure only the
   supported operations needed in the disposable environment using
   [Work IQ policy governance](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp).
   Do not bypass a denial or broadly enable writes just to make a demo pass.

Per-tool approvals are disabled; OAuth consent, administrator consent, source
authorization, and tenant policy are **not** disabled.

> **Important: Baseline Foundry connection OAuth Scopes**
>
> ```text
> api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask offline_access
> ```
>
> Copy the entire space-separated value into the connection's **Scopes** field.
> `WorkIQAgent.Ask` is the delegated API permission granted in Entra; the OAuth
> request uses its fully qualified `api://workiq.svc.cloud.microsoft/` prefix.
> `offline_access` requests refresh-token access. Do not substitute Microsoft
> Graph scopes, a bare `WorkIQAgent.Ask`, or `.default` for this documented
> delegated connection setup. See the
> [official Foundry quickstart's OAuth fields](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/foundry#connect-the-work-iq-mcp-tool-in-foundry).

### Optional action scope: `WorkIQ.Act` versus `WorkIQAgent.Ask`

**The documented permission is `WorkIQ.Act`, not `WorkIQAgent.Act`.** The
[Work IQ permissions reference](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/permissions)
distinguishes them as follows:

| Delegated permission | What it authorizes | Important distinction |
| --- | --- | --- |
| `WorkIQAgent.Ask` | Ask Work IQ agents questions and receive responses on behalf of the signed-in user | Includes read **and write** access to Microsoft 365 resources accessible to those agents; it is **not a read-only scope**. |
| `WorkIQ.Act` | Use Work IQ to read and make changes to Microsoft 365 data the signed-in user can access | Explicit data-action permission; it does not replace the agent-question permission or bypass source permissions and tenant policy. |

To opt into the additional action permission while retaining agent questions:

1. In the **same Entra app registration**, add **Work IQ > Delegated permissions >
   `WorkIQ.Act`**, keep `WorkIQAgent.Ask`, and grant admin consent for both.
2. Replace the Foundry connection's **Scopes** field with this complete value:

   ```text
   api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask api://workiq.svc.cloud.microsoft/WorkIQ.Act offline_access
   ```

3. Reconnect/re-authorize Work IQ as the intended user so the new permission is
   included in the OAuth grant. Changing this README does not change the connection.
4. Verify the intended operation against the live tool schema and tenant policy.
   Both permissions are delegated and require admin consent; neither grants
   access beyond the signed-in user's permissions.

Adding `WorkIQ.Act` is an explicit permission expansion, **not** a switch that
automatically enables every mutation. Tenant policy can still block writes,
and `require_approval="never"` only controls per-call approval prompts. Keep
the baseline scopes unless the intended operations require the action permission.
For genuinely read-only data access, the reference separately documents
`WorkIQ.Read`; do not assume `WorkIQAgent.Ask` enforces read-only behavior.

### Upload the internal guidelines

Manually upload these fictional Markdown files from
[`../enterprise-architect-prompt-agent/internal-guidelines/`](../enterprise-architect-prompt-agent/internal-guidelines)
to a document library in your disposable SharePoint site:

- `governance-and-cost.md`
- `platform-security.md`
- `reliability-and-operations.md`

Confirm each participant can read them through Work IQ. Include the site URL
and guideline folder or file links in architecture prompts:

```text
Use the internal guidelines in <guideline-folder-link> on <site-url> to design
an Azure architecture for supplier invoice automation.
```

Creation does not upload files, build an index, or validate their presence.
Keep confidential and prompt-injection fixtures outside the shared guideline folder.

## Configure and create

```bash
cd samples/microsoft-enterprise-architect-prompt
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your project endpoint, deployment, and Work IQ connection name.
set -a
source .env
set +a
python -m app.create
```

Creation validates the Work IQ connection target and creates an immutable agent
version. It prints the version for invocation and cleanup. Work IQ is required;

## Invoke

```bash
python -m app.invoke --version <new-version>
python -m app.invoke --version <new-version> \
  "Find the email with subject Workshop - Invoice Automation Requirements in my mailbox. Use its requirements to design an Azure architecture."
python -m app.invoke --version <new-version> \
  "Read the requirements in my Teams chat <chat-id> and propose an Azure architecture."
python -m app.invoke --version <new-version> \
  "Read my upcoming workshop architecture review meeting and summarize its agenda. Do not modify my calendar."
python -m app.invoke --version <new-version> \
  "Retrieve <SharePoint-document-url> through Work IQ and summarize its architecture requirements. Cite the source."
python -m app.invoke --version <new-version> \
  "In <SharePoint-output-folder-url>, check that architecture-review-<unique-suffix>.md does not exist. Create that NEW Markdown file with this synthetic content: Invoice automation review; owner Workshop Team. Read it back to verify. Do not overwrite or share anything."
```

All tools, including mutations, run without tool-use approval prompts or review
flags.

Each invocation uses and deletes its own conversation. `tool_choice="auto"`
permits tool-free refusals. Inspect Work IQ and Microsoft Learn traces to verify
retrieval; links in the answer alone do not prove grounding. Microsoft Learn
supplies current official documentation; keep it distinct from internal policy
and other work context. Do not send private content to public tools.

For OAuth consent, open the exact trusted consent URL surfaced by the tool,
sign in as the intended user, then retry. Tool failures, unsupported operations,
and incomplete responses are errors, not successful evidence.

For document operations, use returned identifiers and live schemas. Check
filename conflicts before creation and verify the resulting file. Prompt-level
checks do not provide an atomic create-only guarantee. Binary content is not
proof that the agent parsed PDF/DOCX text; use Markdown for the end-to-end demo.

`--debug` writes the full response, potentially including private tool results,
to stderr. Use only synthetic data. Conversation deletion does not guarantee
deletion from telemetry or service retention.

## Integrate with Microsoft Teams

Use Foundry's **native publishing** route: no custom bot host, Azure Bot resource,
Agent 365 registration, or embedded credentials are needed in this sample.
Publishing exposes a chat surface; Work IQ separately supplies authorized data.

1. Create a version and complete [WORKSHOP.md](WORKSHOP.md) in the playground.
   Inspect both MCP configurations, full catalogs, and `never`
   approval setting. Verify both reads and permitted writes need no confirmation.
2. Open `mea-prompt-agent` in Foundry. Under **Details > Agent configuration >
   Active version**, pin the tested version. Avoid **Always use latest**.
3. Select **Publish > Teams and Microsoft Copilot**. Use **Microsoft Enterprise
   Architect Prompt** as the display name and a description such as "Workshop
   Azure architecture assistant using Work IQ, including SharePoint; requested
   authorized changes run without confirmation." Supply package version and
   developer metadata.
4. Complete tenant validation/distribution requirements and open a **personal
   chat**. Consent to Work IQ as the intended user. Repeat read, write, and
   denial checks; do not assume project/CLI access implies Teams access.
5. For wider distribution, share with authorized test users or select
   **People in your organization** and obtain administrator approval. Review
   this access expansion first. Alternatively download the generated app ZIP
   and upload it through Teams app management; preserve generated IDs and agent
   sections, and never embed credentials.

Keep private work retrieval in personal chat, not groups/channels: the caller's
access does not imply every viewer may see the result. Mermaid may appear as
code, so explain components/data flow in text too.

For network-isolated projects, follow the documented
[REST publishing flow](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).
Do not disable authentication or open account-wide access as a workaround.
After code changes, create a new agent version and explicitly update the active
Teams version. Metadata changes require a new Teams package version; changing
the active agent version alone does not. See the
[publishing guide](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot).

## Troubleshooting

### Work IQ: invalid scope, consent, or authentication failure

**First check the Work IQ connection's Scopes field. The baseline value is:**

```text
api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask offline_access
```

For the optional action-enabled setup, use the combined value in
[Optional action scope](#optional-action-scope-workiqact-versus-workiqagentask).
**Do not request `WorkIQAgent.Act`: the documented name is `WorkIQ.Act`**, with
the fully qualified OAuth scope `api://workiq.svc.cloud.microsoft/WorkIQ.Act`.

In Entra, verify the **same client app** has **Work IQ delegated
`WorkIQAgent.Ask`**, plus **`WorkIQ.Act` if requested**, with tenant admin consent
for each. A Microsoft Graph permission or
an application permission is not a replacement. Check that the connection's
authorization/token URLs use that tenant and its generated redirect URI is
registered as **Web** on the app.

After correcting scopes or consent, reconnect/re-authorize Work IQ as the
intended participant and retry; existing OAuth sessions may retain old grants.
Do not broaden permissions or disable authorization to work around an error.
Correct scopes do not fix billing-policy or source-access denials; check those
separately. Never paste access/refresh tokens or client secrets into logs.

If questions work but an intended change fails, check whether the operation
requires the optional action permission and whether it is consented and present
in the renewed OAuth grant. Also check tenant mutation policy and the user's
write access. Do not treat successful `ask` calls or tool discovery as proof
that a write is authorized.

### Work IQ: caller tenant has no billing policy

`The caller tenant does not have a billing policy configured for WorkIQ.`
requires Microsoft 365 tenant billing configuration. The Work IQ MCP API uses
**Copilot Credits usage-based billing**; paying for Foundry or assigning a
Copilot license alone does not configure API billing.

Have the tenant administrator open **Microsoft 365 admin center > Copilot >
Cost management**, configure a usage-based spending policy covering **Work IQ
API**, configure its funding source, and include the user signing into Work IQ
with available allowance. For the Copilot Studio billing-plan path, assign that
user to the billing plan. Verify the policy's tenant matches the connection's
OAuth tenant. Retry after activation; reconnect/sign in if needed. Redeployment
is not normally required. Microsoft Learn remains available if Work IQ is
unavailable, but cannot supply Microsoft 365 data.

See [Work IQ tenant enablement](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/enable-work-iq)
and [Copilot Credits billing](https://learn.microsoft.com/microsoft-365/copilot/usage-based-billing-overview-copilot-credits).

### Bot channel/resource name is too long

The Azure Bot resource name limit is **2-64 characters**. It starts with an
ASCII letter/digit; subsequent characters can also include underscores,
periods, and hyphens, but not spaces. Use a short base such as `ea-workshop-bot`
where configurable and leave room for generated suffixes. This is distinct
from the Teams display name; preserve **Microsoft Enterprise Architect Prompt**
where supported. See [resource naming constraints](https://learn.microsoft.com/azure/templates/microsoft.botservice/botservices#property-values)
and [publishing troubleshooting](https://learn.microsoft.com/azure/foundry/agents/how-to/troubleshoot-publish-copilot).

## Safety boundaries

There is **no read-only allowlist or per-call approval gate**. The full catalog
can include deletion, sending, and other mutations if tenant policy permits.
Restrict source permissions and tenant policy to the workshop's intended scope.
Auto-approved calls remove the opportunity to review arguments before execution.
Do not use production mailboxes, calendars, or document libraries.

Prompt instructions require authorized, explicitly requested operations, reject
sabotage/fabricated alerts, treat retrieved instructions as untrusted data,
and require reporting failures. These are **model instructions, not deterministic
authorization or DLP controls**. Read tools can also disclose accessible private
data. Real confidentiality requires source permissions, sensitivity protections,
tenant policy, and applicable DLP controls.

Distinguish a model refusal from source enforcement. A restricted body reaching
the model is already a data-handling event, even if the answer omits it. Pause
on unexpected disclosure or changes.

## Cleanup

Remove published Teams distribution before retiring the agent, then delete only
the version printed by creation:

```bash
python -m app.delete --version <new-version>
```

This does not delete SharePoint files, shared connections, consent, tenant apps,
or the original agent. Manually remove only workshop-created files/data and
revert workshop-only policy changes. Remove unused OAuth apps/connections
separately. For older file-search versions, delete vector stores/uploads only
after confirming no remaining version uses them.

## Local checks

```bash
pip install -r requirements-dev.txt
pytest
```

Tests check serialized SDK configuration (Work IQ and Microsoft Learn, no catalog
filters, approval `never`), required connection validation, noninteractive calls for the
documented tool set, explicit errors, isolated conversation cleanup, and agent
version lifecycle. They do not prove live consent, policy enforcement, retrieval,
mutations, or Teams publishing; record those separately in the facilitator guide.
