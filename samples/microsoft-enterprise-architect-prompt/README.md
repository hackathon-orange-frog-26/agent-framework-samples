# Microsoft Enterprise Architect Prompt

A separate, persistent **Foundry prompt agent** displayed in Teams as
**Microsoft Enterprise Architect Prompt**. It adapts the lifecycle and evidence-based
instructions from the [enterprise architect sample](../enterprise-architect-prompt-agent)
and reuses its fictional policy files. It does **not** modify that agent, depend
on its A2A deployment, or create a Foundry vector store. Upload the fictional
policy files to your workshop SharePoint site for retrieval through SharePoint MCP.

| Tool | Purpose | Configuration |
| --- | --- | --- |
| Web search | Current public context and source-quality exercises | Foundry `WebSearchTool`; no separate Bing connection |
| Microsoft Learn MCP | Validate Azure service claims with official documentation | Public `https://learn.microsoft.com/api/mcp` |
| Work IQ MCP | Read the signed-in user's Outlook Mail, Calendar, and Teams context | Delegated OAuth connection; read-only allowlist; reads auto-approved |
| SharePoint MCP (preview) | Retrieve internal guidelines and project files; create small text/binary files | Separate authenticated connection to `mcp_SharePointRemoteServer`; discovery/reads auto-approved; file creation requires approval |

```text
CLI / Foundry playground / Teams personal chat
                    |
          Foundry prompt agent
           /       |       \             \
     Web search   Learn    Work IQ     SharePoint
                         /   |   \    guidelines/files
                      Mail Teams Calendar
```

SharePoint uses the [SharePoint reference (preview)](https://learn.microsoft.com/microsoft-copilot-studio/mcp-sharepoint-tools)
server, **not Work IQ `/sharepoint` paths**, Graph, or the Foundry SharePoint
grounding tool. Read-only calls are auto-approved; file creation requires
explicit approval. Consent, tenant policy, and source permissions still apply
to all private-data calls. Microsoft currently marks this application-specific
server as **backward-compatibility-only**, not for production or new projects;
this existing workshop deliberately uses it for compatibility with a working
connection. Preview tool names/parameters can change; verify the live catalog
before use. This is a **safe-by-default workshop**, not a demonstration that actually deletes
meetings, sends misinformation, compromises Azure, or bypasses confidentiality.
The [facilitator guide](WORKSHOP.md) covers every requested interaction, expected
outcomes, and evidence to collect.

## Prerequisites

- Python 3.10+, `az login`, a Foundry project, and a tool-capable model deployment
  supporting web search and MCP. Set the actual deployment name;
  the default is `gpt-5.3-codex-2`, as in the original sample.
- **Foundry User** on the project; **Foundry Project Manager** to create the
  MCP connections.
- A disposable Microsoft 365 workshop tenant, two test users, and an administrator
  for MCP consent, policy, and Teams app distribution. Confirm current
  [Work IQ billing/licensing requirements](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/work-iq#prerequisites)
  for your connection path; connector licensing and Work IQ API billing differ.
- This repository checkout, including the original sample's policy directory.
  No original agent needs to be running.

Web search and Microsoft 365 tools have separate billing and data-handling terms. Use only
synthetic workshop data. Public search can transfer data outside Azure compliance
and geographic boundaries; do not put private requirements into search queries.

## Connect Work IQ once

Follow the [Foundry Work IQ MCP quickstart](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/quickstart/foundry).
Use the **MCP** endpoint, not the older `work_iq_preview` A2A tool:

1. Have an Entra administrator provision Work IQ if needed, configure a
   single-tenant app, configure the delegated permissions required by the
   current Work IQ quickstart, and grant admin consent.
   Store its client secret only in the Foundry connection, never in this sample.
2. In your Foundry project, open **Tools > Connect a tool > Catalog**, select
   **Work IQ MCP**, and create `workshop-workiq-mcp` targeting
   `https://workiq.svc.cloud.microsoft/mcp`.
3. Configure delegated OAuth using the app's client ID and secret, tenant-specific
   authorization/token URLs, and the scopes documented by that quickstart.
   Copy Foundry's generated redirect URI into the app's **Web** redirect URIs.
4. Inspect the current
   [tool reference](https://learn.microsoft.com/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)
   and confirm `search_paths`, `get_schema`, and `fetch` are available.
   `create_entity`, `do_action`, `ask`, and all other tools are not exposed.
   All allowlisted WorkIQ calls are read-only and auto-approved.
5. Test sign-in/consent using each participant's **own** user identity. Do not
   share the facilitator's authorized session or use application-only access.
   Azure CLI sign-in authorizes Foundry calls; it does not by itself complete
   Work IQ OAuth consent.
6. Keep Work IQ mutation policy blocked. SharePoint creation no longer uses
   Work IQ and does not require enabling its generic action tools.

Mail, Teams, and Calendar are resource paths on the Work IQ MCP server.
`fetch` reads `/me/messages`, `/me/events`,
and `/me/chats/{id}/messages`; `get_schema` discovers the supported read schema.
Tenant policy may further limit paths/properties. Reads are deliberately bounded,
not a full-mailbox semantic search. If a desired query isn't supported, supply
the test message/chat identifier rather than broadening permissions or enabling
an arbitrary action tool.

## Connect the SharePoint preview server

Reuse your **working authenticated SharePoint MCP connection** in the same
Foundry project. Set `SHAREPOINT_CONNECTION_NAME` to its name. Its target must be
either:

```text
https://agent365.svc.cloud.microsoft/agents/tenants/<tenant-id>/servers/mcp_SharePointRemoteServer
https://agent365.svc.cloud.microsoft/agents/servers/mcp_SharePointRemoteServer
```

For the tenant-specific form, replace `<tenant-id>` with the Microsoft 365 tenant
UUID. Creation reads the server URL from that connection, validates the host,
server ID and tenant UUID (when present),
and binds the resolved connection ID to a separate `SharePoint` MCP tool.
It rejects Work IQ, OneDrive, and unrelated connection targets before creating
an agent version.

A connection configured only in Copilot Studio is **not automatically a Foundry
project connection**. If your working setup is in Copilot Studio, configure and
test the equivalent authenticated remote MCP connection in Foundry first.
The linked SharePoint page documents tools and their endpoint, not a complete
Foundry OAuth recipe. Preserve the authentication, consent, resource audience,
and tenant permissions of your working setup; do not reuse Work IQ scopes or
guess new scopes. No tokens or client secrets belong in `.env` or source code.
This sample consumes an existing connection; it does not provision Agent 365
identities, tenant grants, or a connector.

Verify discovery and an authorized read as each intended participant. Use a
disposable SharePoint site/library with read access to synthetic input files
and contribute access only to the intended output folder. If the endpoint
cannot be used from your Foundry project, report that limitation; the sample
does not silently fall back to Work IQ or another identity.

The default agent has **four tools**. `--without-workiq` omits only
Mail/Calendar/Teams; `--without-sharepoint` omits only SharePoint. Both flags
together omit all M365 access. Without SharePoint, internal guideline retrieval
is unavailable; the agent must report that limitation.

### Upload the internal guidelines

Before using the agent, manually upload these fictional Markdown policy files
from [`../enterprise-architect-prompt-agent/internal-guidelines/`](../enterprise-architect-prompt-agent/internal-guidelines)
to a document library in your disposable workshop SharePoint site:

- `governance-and-cost.md`
- `platform-security.md`
- `reliability-and-recovery.md`

Keep the filenames and requirement IDs unchanged. Grant each participant read
access to this folder, and keep it separate from the output folder used for
agent-created files. Confirm the files can be read through the SharePoint
connection as that participant. Supply the site URL and guideline folder or
file links in your architecture request; the agent asks for the location if
it is missing. For example:

```text
Use the internal guidelines in <guideline-folder-link> on <site-url> to design
an Azure architecture for supplier invoice automation.
```

The creation command does not upload files, build an index, or modify SharePoint.
Do not upload confidential or prompt-injection fixtures to the shared guideline
folder.

### Retrieve and create documents

Use the printed version and replace the placeholders with your workshop site,
library, folder, and source document. Discovery and reads run without approval
prompts or a review flag. The CLI pauses for each SharePoint **file creation**
when `--review-m365-tools` is supplied; review the arguments, then type `y` to
approve or press Enter to deny. Creation approval requires an interactive
terminal and is never automatic.

```bash
python -m app.invoke --version <new-version> \
  "In SharePoint site <site-url>, library <library>, retrieve <document-id> and summarize the architecture requirements. Cite the source."
python -m app.invoke --version <new-version> --review-m365-tools \
  "In <site-url>, library <library>, folder <folder>, check that architecture-review.md does not exist. Create that NEW Markdown file with this synthetic content: Invoice automation review; owner Workshop Team. Read it back to verify. Do not overwrite or share anything."
```

The SharePoint allowlist contains:

- Discovery: `findSite`, `getSiteByPath`, `listDocumentLibrariesInSite`,
  `getDefaultDocumentLibraryInSite`, `getFolderChildren`, `findFileOrFolder`.
- Metadata: `getFileOrFolderMetadata`, `getFileOrFolderMetadataByUrl`.
- Reads: `readSmallTextFile`, `readSmallBinaryFile`.
- Creation: `createSmallTextFile`, `createSmallBinaryFile`.

Use the live tools' parameter schemas and returned site/library/folder/file IDs.
`findFileOrFolder` searches across accessible libraries; prefer exact URLs or
bounded folder discovery when possible. Folder listing returns the top 20
children, so an incomplete listing is not proof that a filename is unused.

**File limit:** use files **smaller than 5 MB**. Text creation passes `filename`,
`contentText`, `documentLibraryId`, and optionally `parentFolderId` (default
`root`). Binary creation passes `filename`, `base64Content`, the library ID,
and optional folder ID. These tools transfer file content directly.
Binary reads return base64, not extracted PDF/DOCX text; there is no binary
parser or document generator here. Use text/Markdown for the end-to-end demo,
or supply valid binary content yourself. Native template creation is not exposed.

Delete, rename, move, folder creation, sharing, and permission-changing tools
are excluded. Creation tools may still overwrite existing filenames depending
on server behavior: the instructions require a filename check, but **do not
provide an atomic create-only guarantee**. Approve only a verified new filename
in a controlled folder, and deny any uncertain/conflicting destination.
Work IQ's `fetch` is still generic: instructions prohibit using it for SharePoint
or mutations, but its allowlist alone cannot enforce a resource-path boundary.
Approvals do not replace source permissions, tenant policy, or DLP.

For Foundry playground/Teams, verify that reads run without approval prompts
and that file creation displays an approval request before execution. If
creation approval is unsupported, use the interactive CLI; **do not** remove
creation approval as a workaround. Pin and republish the tested version, and update the Teams description
to mention approval-gated SharePoint creation. See the SharePoint checks in
[WORKSHOP.md](WORKSHOP.md).

Reference: [SharePoint MCP tool names, parameters, endpoint, and preview limitations](https://learn.microsoft.com/microsoft-copilot-studio/mcp-sharepoint-tools).

## Configure and create

```bash
cd samples/microsoft-enterprise-architect-prompt
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your project endpoint, deployment, and both connection names.
set -a
source .env
set +a
python -m app.create
```

Creation resolves and checks both connection targets and creates an immutable
agent version. It prints the version for invocation and cleanup. Internal
guidelines must already be uploaded to SharePoint as described above; creation
does not validate their presence.

Without a Microsoft 365 tenant, explicitly run:

```bash
python -m app.create --without-workiq --without-sharepoint
```

That mode still calls live Foundry/public tools; it is **not** an offline emulator.
It omits both private MCP servers and cannot demonstrate real mail, calendar, Teams,
or SharePoint access, internal guideline retrieval, document creation, or tenant access denial.
There is no silent fallback to fixtures.

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
Reads and discovery auto-approve in the agent definition, so ordinary retrieval
needs neither a review flag nor an interactive terminal. Use `--review-m365-tools`
for file creation; each creation displays exact arguments for approval or denial.
Without that flag, creation approval requests fail explicitly rather than executing.
The legacy `--review-workiq-tools` flag remains WorkIQ-only and never authorizes
SharePoint creation. The reviewer still handles explicit read-approval requests
from older pinned versions conservatively; it never auto-accepts a request
returned by the service. Unexpected server/tool pairs fail before any prompt.

Run `python -m app.create` to create a new immutable version with this policy,
then invoke/pin the printed version. Existing versions keep their old approval
settings until you switch versions and update the active version for Teams.

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
   Inspect all four tools, both private MCP allowlists and connections,
   and approval UX using the checks above.
2. Open `mea-prompt-agent` in the Foundry portal (the unchanged default agent ID).
   Under
   **Details > Agent configuration > Active version**, pin the tested version.
   Avoid **Always use latest** during a workshop.
3. Select **Publish > Teams and Microsoft Copilot**. Set the name to
   **Microsoft Enterprise Architect Prompt**, publish version `1.0.0`, developer
   metadata, and a description such as "Workshop Azure architecture assistant;
   auto-approved work-context reads; approval-gated document creation; does not execute Azure
   changes or send messages."
4. Choose **Direct publish > Just you** first. Foundry generates the Teams
   package, registers the bot, enables the Activity Protocol, and configures
   Bot Service authorization. Individual-scope users need the relevant Foundry
   permissions. Confirm your tenant's app policies permit installation.
5. Open the published agent in Teams and use a **personal chat**. Complete
   consent for both private MCP connections as the intended user. Verify that
   the working SharePoint authentication mode is supported on this surface;
   do not assume CLI/project access implies delegated Teams access.
   Repeat the mail and calendar read examples
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
Foundry. SharePoint remains available through its separate connection; mail,
Teams, and calendar do not. Add `--without-sharepoint` to omit both private
servers. Do not apply Work IQ billing/scopes troubleshooting to the separate
SharePoint server.

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

The WorkIQ **tool allowlist** excludes creation/action capabilities. A separate
SharePoint allowlist exposes discovery, reads, and small-file creation only.
WorkIQ uses `require_approval="never"` for its read-only allowlist. SharePoint
uses explicit per-tool filters: discovery/reads use `never`, while
`createSmallTextFile` and `createSmallBinaryFile` use `always`.
Instructions restrict creation to new files; filename checks are not atomic.
The generic WorkIQ read tools are not a deterministic SharePoint path boundary.
Auto-approved reads remove the opportunity to review private-data arguments
before execution; restrict source access and use only synthetic workshop data.
Review each creation and rely on source permissions, consent, and tenant policy
for authorization. No Azure execution tool is installed. The public Learn MCP
server also uses `require_approval="never"`; web search needs no MCP approval.

The prompt's confidentiality, injection resistance, and sabotage refusal are
**model instructions, not deterministic authorization or DLP controls**.
Read-only tools can still disclose data the user is allowed to read. Real
confidentiality requires correctly configured source permissions, sensitivity
protections, tenant policy, and applicable DLP controls. SharePoint guidelines
retain their source permissions; grant access only to intended participants.
Keep confidential and injection fixtures outside the shared guideline folder.

Do not treat a model refusal as proof of tenant access enforcement. Use source
permissions and traces to distinguish "denied/not returned" from "retrieved but
not disclosed." A real confidential body reaching the model is already a
data-handling event. Pause the exercise on unexpected disclosure.

## Cleanup

Remove the published Teams app/distribution through your tenant's app management
process before retiring the agent. Then delete only the agent version from this
sample's create output:

```bash
python -m app.delete --version 1
```

The command deletes only the named agent version. It does not remove SharePoint
content, shared project connections, tenant apps, consent, the original
enterprise architect agent, or its resources. Remove workshop-only SharePoint
files manually when no longer needed. For versions created before file search
was removed, separately delete their old Foundry vector stores and uploaded
files in the portal only after confirming no remaining version uses them.
Revoke/delete workshop-only OAuth apps/connections separately when no longer used.

## Local checks

```bash
pip install -r requirements-dev.txt
pytest
```

Tests check serialized SDK tool configuration, separate SharePoint connection routing,
approval/denial and continuation, lifecycle/cleanup behavior, invocation
isolation, error handling, and the absence of file-search provisioning without Azure.
They do not prove model refusal behavior, tenant permissions, OAuth, or Teams
publishing; run the facilitator guide in your configured tenant for those.
