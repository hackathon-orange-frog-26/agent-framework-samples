# Microsoft Enterprise Architect Hosted

A separate **Foundry hosted agent** with the capabilities of
[`microsoft-enterprise-architect-prompt`](../microsoft-enterprise-architect-prompt):
evidence-based Azure architecture, web search, Microsoft Learn MCP, read-only
Work IQ Mail/Teams/Calendar and SharePoint through `WorkIQToolbox` for guidelines,
document retrieval, and approval-gated small-file creation.

Unlike the prompt sample, **your Python code owns the Agent Framework agent**.
Foundry builds the uploaded source ZIP and runs the Responses host on managed
compute. No Docker, container registry, custom bot host, or prompt-agent
deployment is required. The existing prompt agent is not changed or invoked.
The default resource name is `mea-hosted-agent`; the display name for publishing
is **Microsoft Enterprise Architect Hosted**.

```text
CLI / Foundry playground / published Teams personal chat
                         |
          Foundry hosted Python Responses server
                         |
           Agent Framework + FoundryChatClient
                         |
               Foundry model and tools
             /        |        \
        Web search   Learn   WorkIQToolbox
                            Work IQ + SharePoint
```

| Capability | Hosted implementation |
| --- | --- |
| Architecture recommendations | Same instructions and default question as the prompt sample, with a different agent name; assumptions, Mermaid, evidence, requirement IDs, identity/network boundaries, RTO/RPO, operations, and costs |
| Public grounding | Native Foundry `WebSearchTool` and public Microsoft Learn MCP; no Bing connection |
| Work context | `FoundryToolbox` connected to `WorkIQToolbox` version `1`; tools discovered from the toolbox |
| Internal guidelines and files | SharePoint tools discovered from the same toolbox; no direct SharePoint MCP connection |
| Approval | All toolbox calls require explicit approval, including reads and file creation |
| Workshop and Teams | Reuse the synthetic fixtures and exercises; publish this hosted endpoint separately after live checks |

Work IQ and SharePoint use the hosting SDK's `FoundryToolbox` MCP client.
Microsoft Learn remains a native Foundry-managed MCP tool.
The request-scoped factory creates fresh model clients and forwards the hosting
SDK's first-party platform headers to Foundry. The opaque call ID lets Foundry
resolve caller context; no participant token or client secret is copied into
the application or ZIP. `FoundryToolbox` refreshes authentication and forwards
the platform call ID; the Responses host manages its connection lifecycle.
Model response storage is disabled because the hosting infrastructure manages
conversation history. The platform agent identity authenticates the model
call; it does **not** substitute for each user's Microsoft 365 consent.

## Prerequisites and connections

- Python 3.10+ locally; the managed source deployment uses `python_3_14`.
- A Foundry project and a model deployment supporting web search and MCP.
  Use the actual deployment name; the default is `gpt-5.3-codex-2`.
  The shared [`infra/`](../../infra) supplies the project/model, not hosted-agent
  deployment permissions.
- `az login`; **Foundry Project Manager** at project scope for deployment and
  **Foundry User** for invocation. Check current availability and permissions in
  the [hosted-agent source deployment guide](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code).
- Outbound access from the hosted runtime to Foundry and the MCP services.
- A disposable Microsoft 365 workshop tenant, synthetic data, two users, and an
  administrator for consent, source permissions, billing, and Teams distribution.

Reuse the original sample's setup instructions in the **same Foundry project**:

1. [Connect Work IQ](../microsoft-enterprise-architect-prompt/README.md#connect-work-iq-once).
   The target must be `https://workiq.svc.cloud.microsoft/mcp`, not preview A2A.
   Complete delegated consent as each intended user, configure Work IQ API
   billing, and keep mutation policy blocked. In that same Foundry project,
   configure the existing **WorkIQToolbox**, version **1**, to expose the Work IQ
   and SharePoint connections. Restrict Work IQ tools to read-only `search_paths`, `get_schema`, and
   `fetch` before using this sample. Toolbox composition and allowlists are
   managed in Foundry, not enforced by this application's toolbox client.
   Deployment does not create or modify the toolbox.
2. Verify SharePoint discovery/read tools and the intended small-file creation
   tools are already included in `WorkIQToolbox`. Configure their authentication,
   permissions, and allowed operations in Foundry. No separate SharePoint MCP URL,
   connection name, or connection ID is required by this application.
3. [Upload the fictional guidelines](../microsoft-enterprise-architect-prompt/README.md#upload-the-internal-guidelines)
   from `../enterprise-architect-prompt-agent/internal-guidelines/` to your
   disposable SharePoint site. Preserve filenames and SEC/REL/GOV/COST IDs;
   give participants read access. Use a separate controlled output folder.
   Deployment does not upload documents or create a vector store.

Azure CLI login is not Microsoft 365 OAuth consent. A connection configured
only in Copilot Studio is not automatically a Foundry connection. Missing
consent, permissions, billing, or unsupported schemas must be resolved at the
source; the code never substitutes fixtures, another user, or another server.

## Configure and deploy

Run from this directory:

```bash
cd samples/microsoft-enterprise-architect-hosted
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit the endpoint, model deployment, and toolbox name/version.
set -a
source .env
set +a
az login

python -m app.deploy
python -m app.invoke --review-m365-tools
```

Environment files are not loaded automatically; source only trusted shell values.
No tokens or secrets belong in `.env`.

Work IQ and SharePoint use the existing toolbox endpoint:
`<FOUNDRY_PROJECT_ENDPOINT>/toolboxes/WorkIQToolbox/versions/1/mcp?api-version=v1`.
It packages only `main.py`, `requirements.txt`,
`app/__init__.py`, `app/agent.py`, `app/config.py`, and `app/host.py`.
Foundry installs dependencies remotely, creates a **hosted** version advertising
Responses **2.0.0**, and runs `python main.py`. The deployer waits up to ten
minutes for `active`, then routes 100% of the named endpoint to that version.
Existing protocol settings and authorization schemes, including Teams
publishing, are preserved. No routing change happens on provisioning failure.
Failures raise errors; failed versions remain for troubleshooting, while the
temporary local ZIP is always removed.

The runtime receives only non-secret endpoint/model values,
`TOOLBOX_NAME` (default `WorkIQToolbox`), and `TOOLBOX_VERSION` (default `1`).
The old `WORKIQ_CONNECTION_*` and `SHAREPOINT_CONNECTION_*` settings and
`SHAREPOINT_SERVER_URL` are no longer used.
The toolbox URL is built from the configured project endpoint, not a hard-coded
project. Toolbox access and discovery are checked when the agent connects at runtime;
failures are not silently replaced with direct MCP calls.
It does not retrieve connection credentials. Model
selection prefers `FOUNDRY_MODEL_DEPLOYMENT`, then
`AZURE_AI_MODEL_DEPLOYMENT_NAME`, then the sample default.

To omit both private integrations, explicitly disable the toolbox:

```bash
python -m app.deploy --without-toolbox
```

This disables mail/Teams/calendar retrieval, internal guideline retrieval, and
file creation together. The old `--without-workiq` flag is retained as an alias
for `--without-toolbox`; `--without-sharepoint` is no longer supported.
Public tools still make live service calls; this is not an offline mode.

Rerunning deployment creates another version and switches endpoint traffic.
Use `--name custom-mea-hosted` on **deploy, invoke, and delete** to isolate
another deployment. Invocation uses the named hosted endpoint, not
`agent_reference` or the prompt sample's `--version` option. The printed version
can be selected in the portal's active-version settings.

## Invoke and review file creation

```bash
python -m app.invoke --review-m365-tools \
  "Use the guidelines in <guideline-folder-link> on <site-url> to design supplier invoice automation. Cite internal requirement IDs and Microsoft documentation."
python -m app.invoke --review-m365-tools \
  "Read the requirements from my test Teams chat <chat-id>, message <message-id>, and propose an architecture."
python -m app.invoke --review-m365-tools \
  "Read my workshop architecture review meeting agenda. Do not modify my calendar."
python -m app.invoke --review-m365-tools \
  "In <site-url>, library <library-id>, folder <folder-id>, check that architecture-review-unique.md does not exist. Create that NEW Markdown file with this synthetic content: Invoice automation review; owner Workshop Team. Read it back. Never overwrite."
```

All toolbox calls, including reads, require an interactive terminal and
`--review-m365-tools`. The SDK enforces approval locally because toolbox
server-side approval metadata is not an execution gate. This deliberately
replaces the former direct-MCP read-auto-approval behavior, avoiding assumptions
about the toolbox's tool names or composition.
Each call prints the exact tool name/arguments and requires `y` for approval; Enter or
anything else denies it. Missing review flags, noninteractive input, unexpected
server labels, and more than 20 approval rounds fail explicitly. The CLI
validates the entire approval batch before asking anything.

Each CLI invocation starts a **fresh response chain**. It uses `store:true`
because approval continuations need host-managed state, then sends decisions
with `previous_response_id`. Response, session, and approval state can persist
under Foundry's retention settings; this is not the prompt sample's
create/delete-conversation lifecycle. Never share response IDs or user
sessions. `--debug` exposes full responses and potentially private tool data.
Failed/incomplete Responses and MCP errors are not reported as successful answers.
Complete OAuth consent in the trusted Foundry playground as the intended
participant and retry when requested; verify private reads from the hosted
endpoint before claiming Microsoft 365 connectivity.

Use files **smaller than 5 MB** and exact live tool schemas. Binary reads return
base64, not parsed PDF/DOCX content. File-creation tools do not guarantee
atomic create-only behavior: conflict checks are model instructions, not
overwrite protection. A top-20 folder listing is not proof of no conflict.
Approve only a verified new filename in a controlled folder, and verify
creation by reading it back. Exclude delete/move/share/permission changes and
mail/Teams/calendar mutations from the toolbox configuration.

## Workshop, safety, and Teams

Reuse the original [facilitator guide](../microsoft-enterprise-architect-prompt/WORKSHOP.md)
and [synthetic fixtures](../microsoft-enterprise-architect-prompt/fixtures).
Run its architecture, mail, Teams, calendar, public-search, confidentiality,
prompt-injection, and SharePoint approval/denial exercises against
`mea-hosted-agent`. Replace prompt-sample creation commands with `app.deploy`
and omit `--version` from CLI invocations. Record the **hosted version**, user,
surface, source permissions, actual tool traces, and approval outcomes.
The original prompt agent does not need to be deployed.

For Teams, follow the current
[Foundry native publishing guide](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot):
open **mea-hosted-agent**, select the tested active version, and choose
**Publish > Teams and Microsoft Copilot**. Use **Microsoft Enterprise Architect
Hosted**, a short bot resource name if configurable, and a description stating
read-only work context and approval-gated SharePoint creation. Start with
**Just you**, then obtain tenant approval before organization-wide distribution.
Foundry handles bot registration; adding the agent to Teams grants no mailbox
or SharePoint access. For private-network projects, use the publishing guide's
REST path without opening account-wide public access.

Verify delegated consent, distinct participant contexts, and **both approval
and denial** on the hosted playground/Teams surface before distribution.
If a surface cannot present creation approvals or delegated consent, do not
publish it as working: use the CLI for approval testing and record the
surface limitation. Never remove approvals as a workaround. Keep private data
in personal chats, not groups/channels. Mermaid may appear as code in Teams.

Keep Work IQ tools read-only and limit SharePoint mutations to intended file
creation: this agent discovers every tool the toolbox exposes. All toolbox
calls require approval, but this is not a replacement for least-privilege
toolbox configuration. Generic Work IQ
`fetch` is not a deterministic resource-path boundary. Confidentiality,
injection resistance, and no-overwrite rules are model instructions, **not
DLP or authorization enforcement**. Rely on source permissions, tenant policy,
consent, and real protections. Never send private content to public search.
Use synthetic data only. A refusal is not proof of source enforcement; record
unavailable live checks as **not verified**.

## Cleanup

Remove any published Teams app/distribution first, then delete this sample's
agent **and all its versions**, including failed builds and endpoint routing:

```bash
python -m app.delete
# For a custom deployment:
python -m app.delete --name custom-mea-hosted
```

This leaves shared project/model resources, the toolbox, connections, the prompt agent,
and SharePoint content intact. Manually remove only workshop-created files.
Hosted compute, builds, model calls, web search, and M365 tools may incur charges.

## Offline checks

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover toolbox configuration and SDK wiring, public native tool payloads,
toolbox opt-out, ZIP contents, hosted deployment/routing/failure handling,
published protocol preservation, resource cleanup, CLI approvals/denials, and
real Responses-host/toolbox discovery, authentication, call-ID forwarding,
connection cleanup, and approval round trips with mocked HTTP.
They do **not** verify live provisioning, tenant consent/billing, source
permissions, model safety, MCP availability, or Teams publishing. Those require
the live workshop checks above.
