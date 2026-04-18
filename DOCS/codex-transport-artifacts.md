# Codex Transport Artifacts

Codex websocket exchanges use the same per exchange directory as HTTP traffic under the Manicure storage root. The directory name stays timestamp plus exchange id prefix:

`{storage_root}/{YYYYMMDDTHHMMSSZ}-{exchange_id[:8]}/`

The index row still lives in `index.jsonl`. The directory now carries the extra artifacts needed to debug ChatGPT authenticated Codex transport.

## Files

Always present:

- `request.raw`
  - The original inbound client payload. For Codex this is the first captured `response.create` websocket frame.
- `request.ir.json`
  - The normalized `InternalRequest` derived from `request.raw`.

Present when Manicure changed or reserialized the outbound request:

- `request.curated.raw`
  - The exact bytes forwarded upstream after pipeline changes and any breakpoint edits.
- `request.curated.ir.json`
  - The final `InternalRequest` that matches `request.curated.raw`.
- `request.audit.json`
  - The full `OverrideAudit` snapshot used to produce the curated request.

Present for HTTP responses:

- `response.raw`
  - The raw provider response body.
- `response.ir.json`
  - The parsed `InternalResponse`.

Present for Codex websocket exchanges:

- `transport.json`
  - Structured transport capture with:
    - websocket upgrade request and response metadata
    - close summary
    - every captured websocket frame, including direction, dropped state, decoded text, parsed JSON when available, and base64 payload for binary frames
  - Sensitive upgrade header values are redacted before write. Header names stay visible so transport debugging still has shape.

## Notes

- Codex exchanges currently persist response stream transport artifacts instead of a parsed `response.ir.json`. The detail API exposes `transport` for inspection, and the index row carries a lightweight `ResStats` summary derived from the captured server frames.
- `request.curated.raw` is intentionally explicit. It records the exact payload Manicure forwarded, which can differ from `request.raw` even when the logical IR did not change because the adapter reserialized the frame.
- Failed websocket upgrades now persist a diagnostic Codex exchange even when no websocket session was established. Those rows use `model=codex/transport-handshake`, store the HTTP failure body in `response.raw`, and keep the upgrade metadata in `transport.json`.
- Legacy `transport.json` rows written before header redaction are sanitized lazily on first read and rewritten in place. That keeps historical exchanges inspectable without returning raw auth material through the API.

## Failure modes and operator checks

The exchange detail API now derives `transport_diagnostics` from the stored
artifacts so operators do not need to infer common failures from raw JSON alone.

### `chatgpt_auth_rejected`

- Trigger: upgrade status `401` or `403`
- Read first:
  - `response.raw`
  - `transport.upgrade.response_headers`
- Check:
  - Codex is authenticated with ChatGPT in the launched environment
  - you are validating the ChatGPT transport path, not the API key harness

### `proxy_trust_failed`

- Trigger: handshake failure body mentions TLS or certificate validation
- Read first:
  - `response.raw`
  - `transport.upgrade.response_status_code`
- Check:
  - the managed Codex child inherited `HTTP_PROXY` and `HTTPS_PROXY`
  - `CODEX_CA_CERTIFICATE` points at a readable merged bundle
  - the bundle contains `~/.mitmproxy/mitmproxy-ca-cert.pem`

### `websocket_closed_abnormally`

- Trigger: websocket close code is not `1000` or `1001`
- Read first:
  - trailing `transport.messages`
  - `transport.close`
- Check:
  - whether the server emitted any frames before closing
  - whether the close followed a normal `response.completed` event

### Fixture corpus

The canonical Codex fixtures live in `api/tests/fixtures/`. The important split is:

- `codex_response_create.json` for request parser and serializer round-trips
- `codex_transport_chatgpt_success.json` for normal ChatGPT transport capture
- `codex_transport_chatgpt_403.json` and `codex_transport_proxy_502.json` for upgrade-failure diagnostics

Keep the API key harness fixture available, but do not let it redefine the product path. The product contract remains ChatGPT-authenticated Codex over `chatgpt.com/backend-api/codex/responses`.
