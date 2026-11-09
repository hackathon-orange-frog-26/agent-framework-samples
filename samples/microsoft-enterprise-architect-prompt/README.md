# Microsoft Enterprise Architect Prompt

A separate, persistent **Foundry prompt agent** displayed in Teams as
**Microsoft Enterprise Architect Prompt**. It adapts the lifecycle and evidence-based
instructions from the [enterprise architect sample](../enterprise-architect-prompt-agent)
and reuses its fictional policy files. It does **not** modify that agent, depend
on its A2A deployment, or share its vector store.

| Tool | Purpose | Configuration |
| --- | --- | --- |
| Web search | Current public context and source-quality exercises | Foundry `WebSearchTool`; no separate Bing connection |
| Microsoft Learn MCP | Validate Azure service claims with official documentation | Public `https://learn.microsoft.com/api/mcp` |
| Work IQ MCP | Read the signed-in user's Outlook Mail, Calendar, and Teams context | Delegated OAuth project connection; only `fetch` and `get_schema` exposed |
| Foundry files | Internal architecture standards | A new vector store populated from the original sample's `internal-guidelines/*.md` |

```text
CLI / Foundry playground / Teams personal chat
                    |
          Foundry prompt agent
           /       |       \            \
     Web search   Learn    Work IQ     File search
                         /   |   \     shared policy
                       Mail Teams Calendar (read-only)
```

This is a **safe-by-default workshop**, not a demonstration that actually deletes
meetings, sends misinformation, compromises Azure, or bypasses confidentiality.
The [facilitator guide](WORKSHOP.md) covers every requested interaction, expected
outcomes, and evidence to collect.

## Prerequisites

- Python 3.10+, `az login`, a Foundry project, and a tool-capable model deployment
  supporting web search, MCP, and file search. Set the actual deployment name;
  the default is `gpt-5.3-codex-2`, as in the original sample.
- **Foundry User** on the project; **Foundry Project Manager** to create the
  Work IQ connection.
- A disposable Microsoft 365 workshop tenant, two test users, and an administrator
  for Work IQ consent, policy, and Teams app distribution. Confirm current
  [Work IQ billing/licensing requirements](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq#prerequisites)
  for your connection path; connector licensing and Work IQ API billing differ.
- This repository checkout, including the original sample's policy directory.
  No original agent needs to be running.

Web search and Work IQ have separate billing and data-handling terms. Use only
synthetic workshop data. Public search can transfer data outside Azure compliance
and geographic boundaries; do not put private requirements into search queries.

## Connect Work IQ once

Follow the [Foundry Work IQ MCP quickstart](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/foundry).
Use the **MCP** endpoint, not the older `work_iq_preview` A2A tool:

1. Have an Entra administrator provision Work IQ if needed, configure a
   single-tenant app, add delegated `WorkIQAgent.Ask`, and grant admin consent.
   Store its client secret only in the Foundry connection, never in this sample.
2. In your Foundry project, open **Tools > Connect a tool > Catalog**, select
   **Work IQ MCP**, and create `workshop-workiq-mcp` targeting
   `https://workiq.svc.cloud.microsoft/mcp`.
3. Configure delegated OAuth using the app's client ID and secret, tenant-specific
   authorization/token URLs, and
   `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask offline_access`.
   Copy Foundry's generated redirect URI into the app's **Web** redirect URIs.
4. Keep Work IQ tenant policy's mutation operations blocked. Inspect the current
   [tool reference](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)
   and confirm `fetch` and `get_schema` are available. This sample's exact
   allowlist excludes `create_entity`, `update_entity`, `delete_entity`,
   `do_action`, and delegated natural-language `ask`.
5. Test sign-in/consent using each participant's **own** user identity. Do not
   share the facilitator's authorized session or use application-only access.
   Azure CLI sign-in authorizes Foundry calls; it does not by itself complete
   Work IQ OAuth consent.

Mail, Teams, and Calendar are resource paths on this single Work IQ MCP server,
not three hand-written Graph clients. `fetch` reads `/me/messages`, `/me/events`,
and `/me/chats/{id}/messages`; `get_schema` discovers the supported read schema.
Tenant policy may further limit paths/properties. Reads are deliberately bounded,
not a full-mailbox semantic search. If a desired query isn't supported, supply
the test message/chat identifier rather than broadening permissions or enabling
an arbitrary action tool.

## Configure and create

```bash
cd samples/microsoft-enterprise-architect-prompt
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your project endpoint, deployment, and connection name.
set -a
source .env
set +a
python -m app.create
```

Creation resolves and checks the Work IQ connection target, creates a **new**
vector store, uploads only the shared fictional guidelines, verifies indexing,
and creates an immutable agent version. It prints the version, vector store ID,
and underlying file IDs for cleanup. Failed indexing/creation triggers cleanup
of the newly created store and uploaded files.

Without a Microsoft 365 tenant, explicitly run:

```bash
python -m app.create --without-workiq
```

That mode still calls live Foundry/public tools; it is **not** an offline emulator.
It omits Work IQ entirely and cannot demonstrate real mail, calendar, Teams
retrieval, or tenant access denial. There is no silent fallback to fixtures.

## Invoke

```bash
python -m app.invoke --version 1
python -m app.invoke --version 1 \
  "Find the email with subject Workshop - Invoice Automation Requirements in my mailbox. Use its requirements to design an Azure architecture."
python -m app.invoke --version 1 \
  "Read the requirements in my Teams chat <chat-id> and propose an Azure architecture."
python -m app.invoke --version 1 \
  "Read my upcoming workshop architecture review meeting and summarize its agenda. Do not modify my calendar."
```

Replace `1` with the printed version. Each invocation uses and deletes its own
conversation; no participant context is shared. `tool_choice="auto"` permits
tool-free refusals, unlike the original sample's required-tool invocation.
Instructions require policy and Learn retrieval for architecture answers;
inspect traces to check that the model actually complied.

For OAuth consent, open the exact trusted consent URL surfaced by the tool,
complete sign-in as the intended user, then retry. Tool failures and incomplete
responses are errors, not successful architecture evidence.

`--debug` writes the complete response, including tool outputs, to stderr. Use
only with synthetic data; do not capture real mail in shared logs. Conversation
deletion is not a guarantee of deletion from service telemetry or retention.

## Integrate with Microsoft Teams

Use Foundry's **native publishing** route: no custom bot host, Azure Bot resource,
Agent 365 registration, or embedded credentials are needed in this sample.
Publishing exposes a chat surface; Work IQ separately supplies authorized
Microsoft 365 data. Adding the agent to Teams does not grant mailbox access.

1. Create the agent and complete the facilitator guide in the Foundry playground.
   Inspect all four tools, the Work IQ allowlist, and its OAuth connection.
2. Open `mea-prompt-agent` in the Foundry portal (the unchanged default agent ID).
   Under
   **Details > Agent configuration > Active version**, pin the tested version.
   Avoid **Always use latest** during a workshop.
3. Select **Publish > Teams and Microsoft Copilot**. Set the name to
   **Microsoft Enterprise Architect Prompt**, publish version `1.0.0`, developer
   metadata, and a description such as "Workshop Azure architecture assistant;
   read-only work context; does not execute Azure changes or send messages."
4. Choose **Direct publish > Just you** first. Foundry generates the Teams
   package, registers the bot, enables the Activity Protocol, and configures
   Bot Service authorization. Individual-scope users need the relevant Foundry
   permissions. Confirm your tenant's app policies permit installation.
5. Open the published agent in Teams and use a **personal chat**. Complete
   Work IQ consent as the Teams user. Repeat the mail and calendar read examples
   and the negative cases in [WORKSHOP.md](WORKSHOP.md).
6. To distribute to participants, either share the individual-scope agent link
   with appropriately authorized test users, or choose **People in your
   organization** and obtain Microsoft 365 admin approval. Organization scope
   changes who can call the agent; review that access expansion before using it.
7. Alternatively choose **Download & customize > Download ZIP**, inspect the
   generated `manifest.json` and icons, and upload via **Teams > Apps > Manage
   your apps > Upload an app** if custom apps are allowed. Keep Foundry-generated
   IDs and agent sections unchanged. Do not invent a bot ID or paste API keys
   into a manifest.

Teams may show Mermaid as code rather than a rendered diagram; components and
data flow should also be explained in text. Never demonstrate private mailbox
retrieval in a group/channel: the caller's access does not imply that every
viewer may see the response. Audience-specific DLP is not implemented here.

For projects with public network access disabled, portal publishing isn't
supported: use the documented
[REST publishing flow](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).
It enables a source-IP-filtered public Activity Protocol route without opening
the other project APIs. Preserve existing protocols/authorization schemes when
patching endpoint settings; do not disable authentication or enable account-wide
public access as a workaround.

After code/instruction changes, create a new agent version and explicitly update
the active version for Teams. Updating Teams metadata requires a new package
version; changing the active agent version does not require a new Teams package.
See the [publishing guide](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot)
for current UI and authorization details.

## Troubleshooting

### Work IQ: caller tenant has no billing policy

If the Foundry playground or Teams returns
`The caller tenant does not have a billing policy configured for WorkIQ.`,
configure billing in the Microsoft 365 tenant used by the Work IQ OAuth
connection. This sample calls the **Work IQ MCP API**, which uses **Copilot
Credits usage-based billing**. Paying for the Foundry project or assigning a
Microsoft 365 Copilot license alone does not configure Work IQ API billing.
Connector-specific licensing is a separate requirement for connector-backed
tools.

Ask your Microsoft 365 billing/tenant administrator to:

1. Open **Microsoft 365 admin center > Copilot > Cost management**.
2. Configure usage-based billing and create or update a spending policy covering
   **Work IQ API**. Configure its funding source; pay-as-you-go requires an Azure
   subscription and resource group.
3. Include the **user signing into Work IQ from Foundry or Teams** in the policy
   and ensure that spending allowance is available. If using the Copilot Studio
   billing-plan setup path, assign that user to the billing plan.
4. Confirm the policy applies to the tenant in the connection's OAuth
   authorization/token URLs, not merely the subscription hosting Foundry.

Once the policy is active, retry the request. If needed, reconnect Work IQ and
sign in as the covered user. An agent redeployment is not normally required.
See [Work IQ tenant enablement](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/enable-work-iq)
and [Copilot Credits billing and cost management](https://learn.microsoft.com/microsoft-365/copilot/usage-based-billing-overview-copilot-credits).

To continue the workshop without Work IQ, run
`python -m app.create --without-workiq` and select the newly created version in
Foundry. Public research and internal-guideline retrieval remain available;
mail, Teams, and calendar retrieval do not.

### Bot channel/resource name is too long

If Teams publishing rejects the bot channel registration/resource name, check
the **Azure Bot resource name**, not just the Teams display name. The documented
`Microsoft.BotService/botServices` name limit is **2-64 characters**, inclusive.
It must start with an ASCII letter or digit; subsequent characters can be ASCII
letters, digits, underscores, periods, or hyphens. Spaces are not allowed.
See the [Azure Bot resource naming constraints](https://learn.microsoft.com/azure/templates/microsoft.botservice/botservices#property-values).

Use a short resource name such as `ea-workshop-bot` where the publishing flow
allows you to set it. If the flow generates the name, inspect the rejected name
and shorten its configurable base name, leaving room for any generated suffix.
Do not treat the 64-character resource limit as a Teams display-name or manifest
field limit; those are separate validations. Keep **Microsoft Enterprise
Architect Prompt** as the user-facing name when supported. For other publishing
validation errors, follow the
[Foundry publishing troubleshooting guide](https://learn.microsoft.com/azure/foundry/agents/how-to/troubleshoot-publish-copilot).

## Safety boundaries

The Work IQ **tool allowlist** and tenant-side policy prevent the exposed agent
from mutating Microsoft 365 data. No Azure execution tool is installed. MCP
approval is `never` only for these selected reads and the public Learn server;
this is not an approval bypass for write operations.

The prompt's confidentiality, injection resistance, and sabotage refusal are
**model instructions, not deterministic authorization or DLP controls**.
Read-only tools can still disclose data the user is allowed to read. Real
confidentiality requires correctly configured source permissions, sensitivity
protections, tenant policy, and applicable DLP controls. Uploaded vector-store
files do not inherit mailbox/user ACLs: upload only the shared fictional policy.
The confidential and injection fixtures are deliberately **not** indexed.

Do not treat a model refusal as proof of tenant access enforcement. Use source
permissions and traces to distinguish "denied/not returned" from "retrieved but
not disclosed." A real confidential body reaching the model is already a
data-handling event. Pause the exercise on unexpected disclosure.

## Cleanup

Remove the published Teams app/distribution through your tenant's app management
process before retiring the agent. Then use **only IDs from this sample's create
output**, after confirming no remaining version uses them:

```bash
python -m app.delete --version 1 --vector-store vs_... \
  --files file_... file_... file_...
```

The command deletes the named agent version, optional vector store, and explicit
underlying uploaded files. It does not remove shared project connections, tenant
apps, consent, the original enterprise architect agent, or its resources.
Revoke/delete workshop-only OAuth apps/connections separately when no longer used.

## Local checks

```bash
pip install -r requirements-dev.txt
pytest
```

Tests check serialized SDK tool configuration, lifecycle/cleanup behavior,
invocation isolation, error handling, and fixture separation without Azure.
They do not prove model refusal behavior, tenant permissions, OAuth, or Teams
publishing; run the facilitator guide in your configured tenant for those.
