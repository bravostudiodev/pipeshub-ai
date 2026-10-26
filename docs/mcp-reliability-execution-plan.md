# MCP reliability execution plan

Status: in progress. Phases 0/1 stabilization, 2 credential-refresh hardening,
3 client/session runtime, and the core Phase 4 private catalog-cache integration
are implemented locally, independently reviewed, corrected and tested. Nothing
has been committed or deployed. See "Handoff" below for the checkpoint,
owner decisions and next steps. Proactive catalog notification invalidation and in-turn
registry replanning remain, alongside Phases 5–7. The new SDK still requires a
dependency-base rebuild and provider smoke checks.

## Goal and evidence

Harden the current OddJeeves experience so nontechnical executives can connect
their sources and ask questions without managing tools, sessions or discovery.
Incorporate useful upstream reliability improvements while preserving the fork's
company-specific behavior, employee connection cards, personal Superhuman Docs
tokens, diagnostics, proxy policy and configurable AI gateway.

This is a practical implementation sequence, not a production release program.
There is no canary, cohort rollout, traffic splitting or minimum observation
window requirement. Validate locally and in the existing test environment, run
a real-provider smoke check, then deploy normally when the checks pass.

This plan combines two independent code reviews. The fork's common baseline
with upstream is `64d47c776`. The supplied upstream snapshot at
`~/Desktop/pipeshub-ai-main/` includes the MCP rework in `4d78e5e84` (#4003). The recent fork recovery changes include `d9331fd3e` and
`41016ac38`. Pin the actual donor revision and inspect subsequent fixes before
porting; do not copy from a moving branch.

The first review ran 289 targeted MCP/adapter tests successfully. Additional
in-memory probes demonstrated that an opening-session 401 bypasses recovery,
a timed-out call is replayed, a `Session terminated` MCP error is classified as
unknown, and SDK output validation can discard useful successful results.
Attribution of reported failures, proxy limits and provider-specific failure
rates remain unverified. Use available logs and reproductions in Phase 0 rather
than treating every plausible mechanism as an observed incident. Missing
production-scale metrics must not block the work.

Relevant implementation:

- `backend/python/app/agents/mcp/`: client, discovery, OAuth, refresh, status.
- `backend/python/app/agents/agent_loop/mcp_*`: resolution, loading, execution.
- `backend/python/app/api/routes/{agent,mcp_servers}.py`: attachment and listing.
- `backend/python/app/config/configuration_service.py`: configuration semantics.
- `backend/python/app/connectors/core/base/token_service/mcp_token_refresh_service.py`.
- `backend/python/app/utils/{outbound_http,outbound_proxy}.py`: egress policy.
- `frontend/app/(main)/chat/components/slack-connection-card.tsx`: employee cards.
- `frontend/app/(main)/chat/`: tool catalogs, selections and request construction.

## Handoff — 2026-10-23

### Where the work is

- Branch `PES-1927-ai-knowledge-platform`. Last commit `5b5b8577c` (context
  budget). Everything below is **uncommitted** in the working tree, on top of it.
- The work was restored from the `mcp-tools-auth-hardening` stash, reviewed,
  independently reviewed by a second agent, and corrected.
- Nothing has run against real providers, the Squid proxy or the private
  dependency image.

### What was done after the stash was restored

Review fixes (first pass):
- MCP results go through `agent_loop/mcp_result.py` (ported from upstream):
  images use the request's image admission, binary blocks become short notes,
  output is capped at 200k characters. Base64 no longer reaches the model as text.
- A project's narrowed tool selection is kept while its catalog loads, and
  falls back to the project set if every narrowed tool disappears (an explicit
  empty list now means "no tools" in Node).
- Discovery does not retry after a timeout. Discovery and call log lines carry
  credential- and URL-redacted error text. OAuth refresh failures log the RFC
  6749 error code. Short configuration values are not redacted from messages.
- Granted scopes are compared as sets, so provider reordering is not an
  authorization change mid-turn.
- The connection card resets only when the signed-in identity changes.

Independent review fixes (second pass):
- Shared administrator credentials (`useAdminAuth` with api_token/headers) are
  refused when saved (400), when adopted (409), and reported to users and the
  model as needing per-user sign-in instead of "temporarily unavailable".
- A grant over 96 tool schemas switches to lazy disclosure; any remaining cut
  is logged once per agent and keeps discovery tools and pinned toolsets first.
- `deauthReason="refresh_token_invalid"` (older refreshers) still shows
  "Reconnect needed".
- Instance-scoped MCP selections are never downgraded to bare names, so they
  cannot be re-owned by another instance; bare legacy names go to the longest
  matching type prefix.
- A rotated refresh token that cannot be saved is retried with backoff inside
  the lease, then parked in the process and saved before the next refresh.
- The rejected token is carried into refresh, so a sibling's refresh is reused
  even when the session died.
- Token URLs pass the same address guard as MCP traffic. Lock polling backs off;
  a half-acquired lease is released; in-flight refresh tasks are held strongly;
  malformed token records ask for reconnect; space-separated `WWW-Authenticate`
  parameters parse; the unknown-toolset hint is restored; the OpenAPI spec
  documents instance list/get/delete.

Later decisions:
- The "too large for the model" message no longer includes provider text; the
  raw provider error is logged as `Agent run failed: ... provider_error=...`.
- Tool catalog lifetime raised to 24 hours (see the Phase 4 checkpoint above).

### Verification done

All runs were targeted, single-process (`-p no:xdist`, `nice -n 19`); the
venv still has `fastmcp`/`mcp` 1.30, so new-SDK tests ran with an overlay
(`pip install --no-deps --target <dir> mcp==2.3.0 mcp-types==2.3.0 httpx2==2.12.0`,
then `PYTHONPATH=<dir>`).

- Python: compile clean; Ruff adds no findings against `HEAD`; 959+ MCP,
  refresh, cache, route, lazy-tool, budget and error-classification tests pass.
- Node: `tsc` clean; project-context tests pass.
- Frontend: `tsc` clean; related Vitest suites pass except 31 failures that
  also fail on `HEAD` (chat page mock lacks `GoogleCalendarConnectionCard`,
  session/streaming retry messages, recently-deleted). ESLint: only 4 existing
  `react-hooks/refs` warnings in `use-mcp-oauth-popup.ts`.
- Known failures that also fail on `HEAD`: one prompt-builder test
  (`test_finding_information_references_web_agent_when_composed`) and the
  toolset `TestBuildCompleteOauthConfig` group.
- After the handoff, the owner resolved all three decisions below. A bounded
  context-window rejection retry was added locally; targeted agent-step tests
  pass, but this is not part of the earlier 959+ tests or provider smoke checks.

### Before deploying

1. Rebuild `python-deps`, then the application image (`fork-build.md`).
2. Smoke-test each chat source card through Squid: connect, discover, call,
   token refresh, disconnect/reconnect.
3. Confirm AI Models has the real `contextLength` for each chat model
   (deepseek-v4-flash: 262144), or the budget falls back to 128k.
4. Confirm every stored MCP instance has `orgId` (route-created ones do).
5. Commit.

### Owner decisions

1. Leave existing false "Reconnect needed" markers alone; affected users can
   reconnect. No one-time credential cleanup.
2. On an explicit model context-window rejection, summarize older history and
   retry once if that reduces the request. Preserve the current question and
   tool results; do not retry a partial streamed answer or unrelated 413s.
3. Keep `fetch_tools` returning full schemas in addition to binding them for
   now; avoid risking tool selection to save context.

### Not done yet

- Auth failures reported inside an HTTP 200 (JSON-RPC error or `isError`
  result) do not trigger a token refresh. Needs real provider responses to
  map safely; never infer from text.
- In-turn rediscovery after "tools changed" (Phase 5); calls fail closed today.
- Phases 5–7 of this plan, including card/catalog synchronization.
- Unrelated items raised earlier: users page "Last active" shows the account's
  last-modified time (and `lastLogin` is dropped by the credentials schema);
  Google Calendar 400 root cause; Drive search query hint; artifact retention;
  tool toggle selection race; `/health/services` missing from OpenAPI.

### Working rules for the next agent

- Read `AGENTS.md`, `CLAUDE.md` and `docs/fork-customizations.md` first.
- The owner wants general fixes, no one-off patches, no cross-user sharing,
  recoverable behavior and diagnosable logs without credentials.
- Do not start the app. Do not run parallel or whole-directory test suites on
  the owner's machine; compile, lint and targeted test files only.
- Ask the owner one question at a time, briefly.

## Current checkpoint and fork compatibility ledger

The first stabilization patch removes prose/stale-status auth inference,
propagates failed refresh configuration reads, and distinguishes unavailable
refresh configuration from a permanently rejected grant. It restricts durable
re-auth marking to the rejected snapshot, recovers opening-session 401s, retries
one transient discovery failure, and stops ambiguous timeout/429/5xx replay.
Per-call protocol IDs prevent a different request's HTTP error from authorizing
a retry. Token endpoint errors are parsed structurally, including error
responses with HTTP 200; raw error bodies are no longer embedded in those OAuth
exceptions.

| Fork behavior / evidence | Required intent | First patch treatment |
| --- | --- | --- |
| `d9331fd3e`, `41016ac38`: credential-status and outcome policy | Genuine unusable credentials must not misleadingly stay Connected | Keep status marking, require explicit permanent OAuth rejection and a matching saved snapshot |
| `4575eaf63`, `d9331fd3e`: session recovery | Recover safely without asking employees to debug failures | Retain local dead-client recovery; add opening recovery and safe listing retry; no blind ambiguous-call replay |
| `c009c4018`: provider argument errors | Model must see enough detail to correct a bad call | Preserve the failing call's own response body, not a different request's recorder body |
| Employee cards and documented popup contract | Short user-specific connect/reconnect/revoke; preserve old grant until success | No changes to cards, popup flow, provider matching or scopes |
| `cd431713f`: regenerate no-filter correction | All-tools requests must include authenticated MCP sources | No changes to null/no-filter semantics |
| Proxy/LiteLLM routing and public-web separation | Company egress and model gateway must continue to work; web flag must not disable MCP | No dependency, routing, gateway or feature-flag changes |
| Saved user credentials and diagnostics | Never substitute a different user's grant or expose credentials | Preserve owner paths and existing admin diagnostic boundaries |

Phase 1 validation: the focused MCP/API/refresh suite passed 540
tests. The broader adapter/MCP/API run passed 2,067 tests with two skipped and
five failures. All five failures were reproduced on an untouched HEAD archive:
one artifact sandbox test, two web-prompt tests and two sandbox confinement tests.
No real-provider smoke checks or deployment have been performed.

Phase 2 adds expiring cross-process refresh leases with atomic owner-checked
release, stale-access-token reuse, bounded waits/provider calls, cancellation-safe
persistence and conditional credential writes. Redis, etcd, encrypted wrappers
and the in-memory store implement the conditional-write abstraction; no feature
code opens vendor clients. Refresh and de-authentication can no longer overwrite
a newer reconnect or restore a removed credential through read-then-write races.
The background refresher retains its company-specific floor/threshold behavior,
resets rejection counts per grant and skips no-expiry tokens. New grants bind to
the issuing OAuth client; one previous static client is kept server-side for its
existing grants. Callback save failures are no longer reported as success.

A later independent review reproduced two post-rotation recovery defects:
lease-read failure before the first save could lose issued tokens, and a parked
rotation could overwrite a reconnect that retained the same refresh-token
string. The save path now parks already-issued tokens if lease ownership cannot
be verified (without writing under that lease); recovery checks both the
original credential generation and OAuth token snapshot before applying them.
Focused refresh-coordination regressions cover both cases. A later review
found that catalog migration could still strand a legacy grant's parked
rotation: legacy generations are now established under the refresh lease
before exchanging tokens, with a temporary error on migration failure.

Phase 2 tests include two actual Python processes sharing an atomic test backend,
Redis Lua execution via fakeredis, etcd revision/lease transaction contracts,
encrypted conditional writes, revocation/reconnect races, cancelled callers,
provider deadlines, crashed/expired leases and failed/ambiguous persistence.
These are local tests, not live Redis/etcd/provider deployment validation.
Phase 2's focused config/MCP/API/refresh run passed 1,383 tests with one expected
failure. The broader run passed 2,910 with two skipped, one expected failure and
the same five independently reproduced baseline failures. New files pass Ruff;
modified tracked files add no Ruff findings. Updated MCP OpenAPI paths parse
and their operation IDs are unique. Nothing has been deployed.

Phase 3 adopts the pinned donor's official `mcp==2.3.0` / `httpx2==2.12.0`
client, wire recorder, typed failures and task-owned session lifecycle. The fork
keeps its administrator STDIO commands, per-user grants, proxy/bypass selection,
CA configuration and safe logging rather than importing optional upstream
product restrictions. Chat discovery and execution share one session; dead
clients are evicted, session-ID-backed expiry recovers, and healthy sessions
receive refreshed headers without cancelling their concurrent calls. 5xx/429
and timeout outcomes remain interrupted, never automatically replayed, even
when the failing HTTP response contains a JSON-RPC error body.

Usable mismatched-schema results and post-call validation/listing failures no
longer discard completed work. Source data is not reinterpreted as a generic
success/error envelope; mixed resource blocks survive and oversized output has
an explicit bound. Incomplete pagination fails explicitly. Connection/listing,
progress-aware idle deadlines, absolute maximum duration, cancellation and
administrator timeout overrides have separate contracts. The new HTTP transport
has explicit policy routing, direct DNS pinning, origin restrictions and no
proxy-to-direct fallback. Private administrator endpoints are supported, but
loopback/metadata destinations remain blocked.

Phase 3 validation: **3,470 passed, 2 skipped, 1 xfailed**, with the same five
previously reproduced unrelated sandbox/web-prompt baseline failures. This
includes real local SDK HTTP/SSE/STDIO servers and runtime discovery/session
reuse, expired-session recovery, sibling-call isolation, Stop delivery, timeout
recovery and a simulated provider effect followed by 503 without duplicate
execution. New transport tests cover proxy selection, DNS pinning, private
network boundaries, proxy-only DNS, Squid refusals, CA reload/fail-closed
behavior and credential/log isolation. Changed Python files add zero Ruff
findings; frontend DTO ESLint and OpenAPI parse/field-contract checks pass.
Tests ran with an isolated dependency overlay; the existing venv was not
upgraded. The private dependency base and real providers/proxy topology have
**not** been built or smoke-tested. OpenAPI and frontend DTOs document the
administrator overrides without exposing tuning to employees.

Still pending: Phase 5 model-facing discovery improvements, structured MCP
authentication handling for error results, Phase 6 end-to-end card/catalog
synchronization, and Phase 7 real-provider/deployment checks. Existing falsely
de-authenticated records have not been modified or bulk-reactivated.

### Phase 4 checkpoint: private catalog cache

`catalog_scope.py` provides the authoritative owner/grant/configuration identity.
`catalog_cache.py` stores complete real tool schemas and server instructions in
ConfigurationService expiring keys, namespaced by an opaque scope digest and
schema version. It never enables public sharing or caches results/content. Chat
and workspace MCP instance-tool listings use this service, including agent-key
listing through the shared helper. A valid chat hit does not connect to the
provider; a miss lists on and retains chat's execution session. First execution
after a hit shares one live listing across parallel calls; changed/removed
contracts fail before execution. Authority is re-read around cache use and fill;
generation changes reject old sessions. Authority is checked again immediately
before each tool send, including after opening/validation/recovery. Healthy
sessions accept current OAuth headers without changing grant identity or
cancelling siblings. Legacy generation assignment shares the refresh lease,
so it cannot invalidate persistence of a concurrently rotated refresh token.
Omitted unchanged scopes on refresh retain their previous value; explicit scope
changes still invalidate metadata. A changed contract stays blocked on repeated
calls until explicit rediscovery. Opening/listing 401s use the existing bounded refresh
policy; ambiguous execution is never replayed.

Catalog lifetime is 24 hours by default (`MCP_TOOL_CACHE_TTL_SECONDS`, 0 turns
it off). Shorter provider hints are honored (rounded down; under one second is
not cached). A hint of 0, the protocol default, or an unusable hint gets a
15-minute window (`MCP_TOOL_CACHE_STALE_TTL_SECONDS`). The pre-call live listing
keeps a long lifetime safe. Cache entries, schema shapes and expiry values are
validated; returned metadata is detached from stored objects. Random epoch
tokens are never reused after expiration, so late writes cannot resurrect an
old namespace. Epoch keys outlive every entry (lifetime + 300 s). Fill/queue/
storage waits are bounded to 60 seconds, additionally constrained by caller
budgets. API list discovery retains its 8-second budget; chat uses the computed
instance connection/listing budget. Provider listings are bounded per instance
(4) and per process (64), so one stalled provider cannot block other users;
single-flight is loop/process-local, not cross-replica. Loop/lock registries
are bounded. The pre-call check compares call contracts (name, input/output
schema, annotations), not descriptions, which some providers vary per listing.

Focused validation: **25 cache/session/storage tests**, **15 authority-scope
tests** (including migration versus token rotation), three refresh-scope cases,
a targeted native client notification-race check and selected existing
runtime/API/policy regressions. Only affected tests were selected; no broad suite was rerun.
The six real local SDK runtime HTTP regressions still pass. Tests use the
isolated SDK overlay; no cloud providers, private dependency image or deployed
proxy topology have been tested. Luna performed implementation passes; review
corrected epoch initialization/expiry, stale-schema execution, authorization
races, header rotation and opening recovery, then validated the focused cases.

Automatic replacement of an already-disclosed registry contract/replanning is
still Phase 5 work. Explicit rediscovery can adopt the new contract safely.
Notifications are revision-aware and consumed on live listing/execution;
proactive notification-driven shared-epoch invalidation remains deferred, so a
catalog-only consumer may retain old metadata until the entry expires.
Actual execution revalidates cached contracts before sending a tool request.

## Decisions and non-negotiable boundaries

1. **Harden the fork; upstream is a reference, not the product specification.**
   Before changing behavior, inspect its history, tests and callers to establish
   why it exists and whether it serves a company requirement. Preserve that
   intent while repairing unsafe mechanisms. Adopt upstream changes only after
   checking compatibility; an SDK replacement is a means to reliable operation,
   not an end in itself. If replacement is warranted, port a coherent substrate
   rather than mixing incompatible pieces or maintaining two permanent clients.
2. **Fail closed for content, not by destroying credentials.** A store/network
   failure makes the operation unavailable. It must not invalidate a grant.
3. **Only authoritative evidence changes durable auth state.** Separate
   provider credential rejection, expired OAuth, missing scopes, missing
   credentials, store unavailability, proxy denial and interrupted execution.
   A provider-origin 401 is not universally a permanent failure: OAuth gets a
   bounded refresh attempt; gateway/proxy responses require origin attribution.
4. **Never blindly replay an ambiguous call.** Timeout, 429 or 5xx alone does
   not prove a write did not run. Retry only with evidence of non-execution,
   documented idempotency, or verified read-only semantics. Do not infer
   read-only safety solely from the tool name.
5. **Preserve caller identity throughout.** No admin/shared-token fallback.
   Cache metadata is scoped to organization, instance, credential owner and
   sign-in/config generation. This plan does not introduce a tool-result cache.
6. **Preserve product contracts.** Keep the custom cards, reconnect/revoke,
   Superhuman token flow, administrator-only diagnostics and LiteLLM-compatible
   model routing. Do not add provider-specific prompt hacks.
7. **Security and networking are gates, not later cleanup.** Any adopted SDK or
   HTTP library must obey the fork's proxy, CA, SSRF and logging requirements
   before real-provider testing.
8. **Smooth recovery is the default employee experience.** Recover safe transient
   failures automatically with bounded waits. Ask for reconnect only when user
   action is actually necessary. Keep technical diagnostics with administrators,
   not in executive-facing chat or connection cards.

## Phase 0 — Understand fork requirements and reproduce failures

**Purpose:** establish what must keep working, identify actual failure paths,
and select upstream improvements without discarding intentional customization.

Deliverables:

- Build a short compatibility ledger for each affected customization: original
  purpose, supporting commit/test/provider behavior, required outcome, proposed
  repair and regression test. Cover custom buttons, credential-status writes,
  retry/error handling, provider matching, scopes, callback flow, proxy routing
  and model gateway. A suspicious mechanism is not evidence its intended
  behavior was unnecessary. Ask the owner only where a material requirement
  cannot be established from the repository or observed behavior.
- Keep employee retrieval MCP-only; do not substitute native ingestion connectors
  as a workaround. Preserve existing administrator compatibility paths without
  exposing them as new employee setup requirements.
- Record deployed image/revision, installed SDK versions, query/connectors
  replica counts, model route and effective MCP timeout configuration. Do not
  export credentials or environment secrets.
- Map the path from card authorization through authenticated auto-attachment,
  composer filtering, live discovery, lazy tool selection and execution.
- Add bounded fault-injection fixtures for provider HTTP responses, JSON-RPC
  session expiry, connection resets, output-schema mismatch, concurrent calls,
  KV outages and rotating OAuth refresh tokens. Test real client/transport
  boundaries as well as mocked session-manager branches.
- Establish a fixed query set across the eight employee cards, including
  cross-source questions, prerequisites/ID lookup, pagination and reconnect.
  Record expected source/tool behavior without requiring identical LLM traces.
- Capture safe counters/timings: attempted vs loaded instances, discovery
  errors, tool outcomes, auth transitions by reason, session opens/reopens,
  refresh attempts, retries and p50/p95 latency. Keep tool errors separate from
  transport errors and model-discovery misses.
- Inspect authorized deployment/Squid logs for denial and tunnel duration;
  confirm necessary exact MCP/OAuth hosts. Do not broaden egress as a shortcut.
- Build a donor dependency map: client/wire/errors, refresh/config primitives,
  schema/model changes, cache, OAuth, agent hooks, Node/API and UI contracts.

**Exit gate:** affected fork requirements are recorded, representative faults
are reproducible and upstream candidates have a pinned donor revision. Use a
small repeatable task set and available timings; no formal metrics program or
production benchmark is required before fixes begin.

## Phase 1 — Contain sticky de-authentication and unsafe replay

**Purpose:** address the recent fork regressions with the smallest safe patch.

Deliverables:

- Preserve the purpose of the fork's credential-status changes: a genuinely
  invalid connection must not misleadingly remain Connected. Repair the evidence
  used for that transition rather than deleting status handling wholesale.
- Replace substring-based auth decisions with typed, operation-specific
  failures. Instance IDs, URLs, timeout text and unrelated provider prose must
  never determine credential validity. Account for authentication failures
  returned as MCP error results as well as raised exceptions; ordinary tool
  argument errors must remain correctable without signing the user out.
- Make credential/config reads distinguish successful absence from failed
  reads. Use explicit error propagation on sensitive reads without globally
  changing unrelated `get_config` callers.
- Split `MCPTokenRefreshError`'s meanings: configuration incomplete, record
  missing/revoked, lock/store unavailable, provider temporarily unavailable,
  and permanent refresh rejection cannot all mean `REAUTH_REQUIRED`.
- Permit durable re-auth marking only after verified permanent rejection of
  the same credential generation that failed. Never invalidate a newer grant
  that arrived during recovery. Preserve an audit reason without raw secrets.
- Handle 401 during session opening; distinguish 403 insufficient scope and
  proxy policy denial from expired authentication. Read-only grants must not
  be escalated automatically to satisfy a tool.
- Associate status with the failing operation/exception, not the session's last
  response. A benign listener GET 404/405 cannot classify an unrelated timeout.
- Preserve useful automatic recovery while removing blind timeout/transport/5xx
  replay. Retry safe discovery, verified read-only work and proven pre-execution
  failures within a bounded budget. Where execution is uncertain, report an
  interrupted call and evict an unusable session for subsequent work. Do not
  turn every transient read failure into a manual retry/reconnect burden.
- Review existing incorrectly marked records. Do not bulk-flip
  `isAuthenticated=true`: the same state includes genuine revocations. Restore
  only where evidence supports it, otherwise guide the affected user through
  reconnect without deleting the saved grant in advance.

Tests/gate:

- Store timeout, transient refresh endpoint failure and listener 405 do not
  de-authenticate a user; strings containing `401`/`expired` do not either.
- Actual permanent refresh rejection produces an actionable reconnect state.
- Opening 401 follows bounded OAuth recovery. Scope denial does not trigger a
  refresh loop. New authorization is not overwritten by stale failures.
- An ambiguous timed-out write is executed at most once by our retry layer.
- Cross-user and cross-org denial still hold; no failed operation returns
  unauthorized content.

**Checkpoint:** a small, independently testable stabilization patch with safe
transition logging. No dependency migration or separate deployment is required
for this phase.

## Phase 2 — Harden token refresh across services and replicas

**Purpose:** stop refresh-token rotation races and credential resurrection.

Deliverables:

- Port upstream's shared refresh serialization and stale-access-token check,
  using configuration-service abstractions backed by atomic create-if-absent
  and TTL, with bounded lock waiting and ownership-aware release. Validate
  atomicity on Redis and etcd; do not emulate a lock with get-then-set.
- Keep local locks as an optimization, not the concurrency guarantee. Lock
  contention/expiry/store failure must not be treated as rejected credentials.
- After refresh, re-read the current credential generation: do not restore a
  disconnected record or overwrite a newer reconnect/refresh. Explicitly
  document remaining compare-and-set limitations and test the supported
  concurrency guarantees rather than assuming upstream solves every race.
- Check persistence success, handle token rotation safely, and preserve the
  OAuth client/token endpoint that actually issued the grant. Do not switch
  clients merely because an administrator saved a newer client configuration.
- Keep background refresh, manual refresh, discovery and execution on the
  same orchestration path. Preserve no-expiry token behavior and bound retries.

Tests/gate:

- Separate processes/replicas race on one rotating token: one refresh wins,
  waiters use the fresh grant, and no rotated-out token is persisted.
- Disconnect and reconnect during refresh never resurrect/overwrite credentials.
- Lock-holder crash, lock timeout, failed persistence and unavailable store are
  tested, including generation changes and non-OAuth instances.
- Existing per-user/service-account compatibility paths retain their own
  owners; employee cards never adopt service-account credentials.

## Phase 3 — Adopt compatible upstream client/session improvements

**Purpose:** address structural transport weaknesses without breaking required
fork behavior. Use Phase 0's compatibility ledger to decide the implementation,
not an assumption that every upstream change is automatically better here.

Deliverables:

- Review the official SDK client against the actual hosted providers, proxy,
  dependency image and fork contracts. Prefer its coherent client/wire/failure/
  lifecycle/session implementation where it resolves the reproduced structural
  faults. If migration is incompatible, document the concrete blocker and
  implement an equivalent tested repair; do not leave a confirmed failure
  unresolved merely to avoid migration. Use the donor's tested dependency set
  as the starting point, then verify compatibility in this fork.
- Cover protocol negotiation, request attribution, server-refused sessions,
  dead-client eviction, reopening, concurrent calls and isolated failures.
  A call failure must not poison every later call in the turn.
- Discover on the same session that executes calls. Handle opening and listing
  failures under the same explicit recovery contract; safe discovery may be
  retried once even though ambiguous execution may not.
- Preserve usable results when output validation fails. Avoid post-execution
  discovery/validation turning successful execution into a retryable failure.
- Port bounded result handling, cancellation propagation, progress-aware call
  timeouts, an absolute maximum duration and per-instance timeout configuration.
  Keep connection/listing/call/HTTP-read timeout meanings separate.
- Integrate `httpx2` traffic explicitly with `OUTBOUND_PROXY_URL`, bypass rules,
  CA settings, SSRF enforcement and redacted request correlation. Existing
  `httpx` monkeypatches do not automatically cover a different HTTP library.
- Remove superseded FastMCP retry/session code and dependencies after parity;
  retain one execution path, not two implementations selected per provider.
- Document per-instance configuration in Python models, Node/OpenAPI and UI
  only where needed; employee cards must not expose transport tuning.

Tests/gate:

- Session expiry with a real session ID reconnects; an initial endpoint 404 is
  reported as endpoint/config failure, not retried as expired-session evidence.
- One failed parallel call does not cause duplicate execution of its siblings.
- Useful mismatched-schema results survive. Stop reaches a running provider.
- Slow progress-emitting calls survive the normal idle deadline but stop at
  their absolute deadline. Listing pagination is complete or explicitly fails.
- Proxy-required traffic cannot silently go direct; policy denials, private
  network rules, redirects and CA validation work in the deployed topology.
- Rebuild the private Python dependency base before the application image;
  verify installed versions in the resulting image, per `docs/fork-build.md`.

## Phase 4 — Port the user-bound catalog cache

Checkpoint: private catalog caching is integrated with chat and MCP API tool
listing. See the Phase 4 checkpoint above for test evidence and limitations.
**Purpose:** remove most discovery handshakes and inconsistent listings.

Deliverables:

- Port one shared catalog service used by chat, workspace, agent builder and
  project/composer listings. Store actual schemas and server instructions,
  never name-only fallback tools or tool responses.
- Scope cache pointers to organization, instance, owner/sign-in generation,
  endpoint/config generation and schema version. Reconnect, revoke, config
  changes, TTL and tool-list-changed events invalidate the appropriate entry.
- Start with private per-owner cache behavior. Do not enable upstream's public
  catalog-sharing optimization without separately proving its isolation rules.
- Revalidate once before first execution where needed. Parallel first calls
  share one validation. A removed/changed tool must not execute with a stale
  contract; update the catalog and let the current run rediscover/replan safely
  where possible, rather than requiring the employee to send another message.
  If the turn cannot recover, explain the limitation honestly.
- Bound listing concurrency and deadlines; apply a single-flight policy to
  duplicate refreshes. Cache failure remains a recoverable service problem,
  not permission to use another identity or invalidate credentials.

Tests/gate:

- Repeated catalog-only turns make zero provider discovery connections on a
  valid cache hit. One uncached listing serves execution's session too.
- Users/orgs/sign-ins/config versions never see one another's private schemas.
- Revocation and reconnect invalidate immediately; TTL and notifications work.
- Changed schemas and a failing cache backend do not produce schema-less tools.

## Phase 5 — Port model-facing tool discovery improvements

**Purpose:** improve choosing and correctly invoking tools after catalog load.

Deliverables:

- Port collision-safe namespaces/groups and backward-compatible attachment
  matching. Do not silently drop duplicate-type instances as the current
  assistant auto-attachment path does. Keep exact instance identity through
  selection and execution; test saved full names and raw names.
- Port app-aware `search_tools` ranking and concise capability-query guidance.
  Evaluate across all sources, not with provider-name prompt workarounds.
- Pass server instructions to the model as untrusted source/tool guidance,
  subordinate to application authorization and safety rules.
- Port bounded schema normalization, reference expansion and a provider-safe
  schema shape. Preserve server validation as the final input authority.
- Port the request tool-count budget and bounded lazy loading. Whole-server
  loads over budget should guide targeted search, not fail the LLM request.
- Preserve clear unavailable-source reasons for assistant attachments that
  have no saved tool list. Failed discovery should not look like a nonexistent
  capability or suggest an unrelated native ingestion connector.

Tests/gate:

- Cross-source queries find the named apps' relevant tools; prerequisites and
  tool errors are recoverable without loops. Compare against Phase 0 tasks.
- Duplicate instances, renamed instances and legacy saved selections work.
- Large catalogs remain within the model/provider tool limit. Schemas work
  through the internal OpenAI-compatible gateway, not just a hosted vendor.

Phase 5 partial checkpoint (uncommitted, not deployed): duplicate-type
assistant instances are no longer silently discarded. Tool/group collisions
use stable per-instance aliases (also for overlapping type prefixes and
provider names that exceed model function-name limits) while scoped composer
selection keeps the instance ID on the wire; bare legacy selections only reach the first sorted
instance of a duplicate type. Project settings now save scoped MCP keys and
Node enforces exact scoped intersections; bare legacy project grants reach
at most one first-sorted matching instance (including cross-type flattened-name
collisions) and migrate when edited. Explicit empty selections stay empty. Cross-source and
real-provider checks remain.
Interactive search
uses app-aware ranking and concise cross-source query guidance; failed attached
sources return bounded unavailable/reconnect diagnostics, including when another
source matches. `fetch_tools` and `search_tools` limit visibility growth to 96
tools; whole-group over-budget loads direct the model to targeted search, and
turn-time schema projection caps oversized initial/eager grants. Complete named
apps now outrank candidates matching only a shared provider word (for example,
Google Drive rather than Google Calendar on a Drive query). Collision-safe
end-to-end namespace and saved-selection verification, and provider-safe
schema normalization are **not complete**. Successfully discovered server instructions
are shown in the prompt as bounded, explicitly untrusted source guidance.
MCP schema expansion now has depth/node/size limits; an unrepresentable tool
is skipped before it can poison the model request. Full provider-safe schema
compatibility still requires gateway smoke checks.
The Python dependency base and real-provider/gateway checks are still pending.

Phase 6 partial checkpoint (uncommitted, not deployed): chat project/catalog
and universal MCP/Actions caches now partition by JWT user and organization,
with no caching when identity is unknown. Successful employee-card OAuth,
personal-token save and revoke invalidate the MCP catalog and trigger project,
settings and composer refetch; stale in-flight fills are discarded. Employee
OAuth reconnection now verifies an opaque per-user grant version changed;
identity switches cancel the in-flight popup and clear token drafts. After the handoff, successful workspace credential saves/revokes and instance
edits also invalidate browser catalogs; the agent-builder personal MCP sidebar
responds only to verified changes, not arbitrary OAuth popup messages. Its
in-flight listing guard prevents stale grant/identity responses, and failed
listings show a load error instead of "no servers". The universal MCP catalog
checks grant revision when its panel remounts, even if the event was missed
while unmounted. Full explicit status-state
presentation and OAuth step-up/client-auth work remain open. These claims
still need live UI integration verification.

## Phase 6 — Integrate employee UI and OAuth hardening

**Purpose:** make status, discovery and recovery agree without losing fork UX.

Deliverables:

- Publish explicit safe states: not configured, not connected, authorized,
  temporarily unavailable, permission required and reconnect required. Keep
  saved authorization distinct from the most recent discovery outcome.
- On connect/reconnect/disconnect, invalidate/refetch affected card, composer,
  project and builder catalogs. Scope browser caches to the signed-in user/org
  and clear on identity changes. A TTL alone is not an invalidation mechanism.
- Preserve null/no-filter semantics for all-tools requests, regeneration and
  follow-ups. Explicit selections should remain intentional and must not
  silently exclude newly connected sources through stale catalog state.
- Preserve popup origin/window verification, Start over, kept-old-grant until
  successful callback, and user-bound Superhuman token reconnect/revoke.
- Port applicable OAuth improvements: protected-resource discovery and
  challenges, resource targeting, client-auth-method support, issued-client
  tracking and readable errors. Add missing-scope step-up only within the
  source's approved permission policy; do not auto-widen read-only scopes.
- Keep admin-only provider configuration, safe per-user status payloads,
  organization-scoped diagnostics, cleanup on owner deletion and credential
  redaction. Sync any changed HTTP contracts with Node and OpenAPI.

Tests/gate:

- Connect and use a source immediately without reloading. Reconnect/revoke
  updates every relevant catalog while retaining credential isolation.
- A temporary discovery failure is not rendered as permanent disconnection.
- One unavailable source does not prevent answering from other authorized
  sources. State missing coverage when relevant; never imply the unavailable
  source was searched or invent its results. Do not weaken custom-agent/tool
  requirements silently to achieve partial success.
- All eight cards work, including Superhuman token errors and Google read-only
  scope denial. No OAuth client secret appears in employee API payloads.
- Existing conversation, project, custom-agent and regenerated turns retain
  their intended source selections.

## Phase 7 — End-to-end smoothness checks and normal deployment

**Purpose:** verify the complete executive experience, not just isolated backend
fixes. No canary, traffic splitting or staged user rollout is required.

Deliverables/gates:

- Run Python MCP/adapter/API/auth/config tests, Node proxy/OpenAPI tests and
  frontend card/catalog/selection tests, followed by `scripts/verify.sh` for
  locally available suites. Do not substitute only mocked happy-path tests.
- Exercise a real fault-injection MCP server through the deployed proxy:
  HTTP/SSE as applicable, expiry, listener 404/405, 401/403/429/5xx, reset before
  and after send, malformed output, slow progress and concurrent requests.
- Exercise real providers with authorized test accounts: Slack, Notion, Miro,
  Atlassian, Gmail, Drive, Calendar and Superhuman Docs. Include at least one
  automatic expiry/refresh cycle and a two-user access-denial scenario.
- Run a short, repeatable nontechnical-user walkthrough: open chat, connect a
  source, ask an ordinary question, ask across multiple sources, continue the
  conversation, and reconnect/revoke. Repeat after an idle period/token expiry,
  with one source temporarily down and after a service restart. The user must
  not need to discover tools manually, refresh the page, configure OAuth fields
  or understand session errors. Include project/custom-agent flows where used.
- Compare the fixed task set with Phase 0 for successful retrieval, unnecessary
  reconnects, repeated calls and obvious latency regressions. This is a practical
  before/after check, not a production-scale benchmark or observation window.
- Require zero false durable de-auth transitions in the fault matrix, zero
  application-induced duplicate writes in injected ambiguous failures, zero
  cross-user leakage, and no proxy bypass. Measure discovery availability,
  tool success by failure category, retries and p95 turn latency separately.
- Build and deploy normally after the relevant checks pass. Keep a compatible
  previous application/dependency image for straightforward recovery; retain
  credentials and discard only new versioned catalog keys if reverting. Do not
  require a rolling upgrade: a controlled restart is acceptable. Test mixed
  versions only if the chosen deployment method actually overlaps them.
- Update `docs/fork-customizations.md`, MCP setup/build docs, operator runbooks,
  and new configuration defaults after implementation, not as if this plan
  were already shipped.

## Implementation order and dependencies

| Work package | Contents | Dependency |
| --- | --- | --- |
| A: understand and stabilize | Phases 0–1 | Preserve documented fork intent |
| B: credential safety | Phase 2 | Phase 1 error/state contract |
| C: runtime and performance | Phases 3–4 | Compatibility review, shared config primitives, dependency image if changed |
| D: discovery and seamless UX | Phases 5–6 | Stable runtime/cache contracts |
| Finish | Phase 7 walkthrough and normal deployment | Relevant automated and real-provider checks pass |

These are implementation checkpoints, not four mandatory releases. Keep changes
reviewable and test each package; deploy the completed work normally, or deploy
an early stabilization fix if useful. Do not impose cohort management or a
production operations program.

Requirements and end-to-end checks apply throughout. UI work and ranking
fixtures may proceed in parallel once backend contracts are agreed, but do not
ship a cache/UI contract mismatch. Completion means the normal executive user
journey works smoothly, not merely that upstream files were copied or unit
tests pass.

## Explicit follow-ups, not prerequisites to reliability restoration

Upstream also adds personal-server management, per-tool approvals, parked-turn
resume, CIMD and additional product UI. These are not required to fix the
reported regression and should not silently enter the runtime port. Record each
as a separate adoption decision with its security, compatibility and UX tests.

Per-tool approvals are especially valuable if hosted servers advertise writes,
but require the full approval/resume/exactly-once contract; copying only the
approval hook is unsafe. Until an approved write policy exists, preserve source
read-only grants and existing controls. Keep new upstream SSRF, secret-handling
and credential-isolation protections that are dependencies of the port rather
than deferring them with optional product features.
