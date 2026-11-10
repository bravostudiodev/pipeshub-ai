# Built-in chat image analysis plan

## Scope

Add an `analyze_image` backend tool for image attachments in the current chat.
The text-only chat model selects an attachment; the tool loads the image under
the authenticated caller's authority, asks the configured vision model for a
general description, and returns that text in the same agent run. No employee
configuration or MCP server is required. HTML and PPTX rendering and visual QA
are deferred until the coding sandbox is available. The analyzer must not
pretend to render documents or accept arbitrary URLs or image bytes from the
model.

## Implementation sequence

1. Trace the authoritative current-chat attachment references for every chat
   entry point, including follow-up history and shared conversations. Verify
   that any client-supplied attachment/history references cannot establish
   conversation membership on their own. Identify the authenticated caller for
   service-account agent runs; never use a service account's broader authority
   to read an employee attachment.
2. Define a stable tool argument referencing an attachment, expose authorized
   current and historical image references to the text model, and resolve the
   selected reference only after checking both chat membership and the caller's
   existing record access. Reload and recheck at execution time; fail closed.
3. Use the stored image blocks or original bytes, accepting only validated
   PNG/JPEG/WebP data (subject to actual upload support). Reject remote URLs,
   malformed images, excessive encoded/decoded size and pixel dimensions.
   Analyze one image per call; enforce a timeout and a concise output limit.
4. Select the existing server-side vision model through the established model
   configuration and client factory, preserving LiteLLM gateway and outbound
   routing. Confirm which configured role/model is intended; do not silently
   send images to a text-only fallback. Return a safe error on configuration,
   timeout or provider failure without logging image bytes or provider secrets.
5. Register the built-in in the agent factory before tool grants are computed.
   Ensure it remains visible under lazy disclosure and tool-count limits and is
   usable in relevant flat, composed and orchestrated runs. Add concise prompt
   guidance for image inspection and explicitly distinguish document rendering.
6. Add unit and integration tests for uploaded and pasted images, follow-up
   attachments, cross-user and cross-conversation denial, missing permission
   infrastructure, invalid/unavailable images, limits, provider failure and
   successful handoff. Verify the text-only model never receives image bytes.
   Document configuration and limitations in `docs/fork-customizations.md`.

## Known dependencies and open decisions

- Upload and paste share the frontend upload path. The standard existing-chat
  streaming controller reads previous messages from persisted conversation
  history, but other paths accept `previousConversations` from request bodies.
  References supplied by an untrusted client alone are not proof of chat
  membership. The Python agent context does not independently establish that
  provenance, so a trusted conversation-membership mechanism must be wired
  before the tool can safely be enabled.
- `caller_can_read_virtual_record` permits an explicit organization-edge
  fallback for service-account uploads. The new resolver disables that fallback
  and checks the authenticated caller, but the graph ACL implementation can
  itself recognize organization grants. Therefore the separate authoritative
  conversation membership check remains essential; missing identity or
  membership authority must fail closed.
- `image_analysis_resolver.py` provides a fail-closed loader. A scoped Node
  service endpoint checks persisted user-query attachments in caller-owned
  sessions, and the registered tool calls it through the Python client. Shared
  conversations are intentionally denied by this initial membership endpoint;
  support requires a separate authorization design and tests. Factory wiring
  tests run against the pinned MCP runtime; a live chat and gateway test still
  requires a running deployment.
- `image_analysis_input.py` now validates stored data URIs independently of
  authorization; it is not registered as a tool and must only be called after
  membership and access checks. Its input limits are 5 MiB and 20 million
  pixels, and it rejects animated images.
- Image analysis selects the unique AI Models entry named by
  `IMAGE_ANALYSIS_MODEL_NAME` (default `qwen3-vl-32b-instruct`) and uses its
  existing provider configuration. The selected entry must be multimodal; no
  chat, indexing, or default model fallback is allowed. The helper has a
  45-second deadline, bounds findings, and hides provider errors.
- Existing browser screenshot code is optional and is not a secured HTML
  artifact renderer. Rendering and image-artifact handoff are deliberately out
  of scope for this phase.
