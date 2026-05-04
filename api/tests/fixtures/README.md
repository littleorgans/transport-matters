# Codex Fixture Corpus

These fixtures pin the Codex transport contract Transport Matters currently
supports.

- `codex_response_create.json`
  - Canonical `response.create` request payload used for parser and serializer round-trip tests.
  - Transport-neutral on purpose, so it remains usable for the internal API key validation harness.
- `codex_transport_chatgpt_success.json`
  - Representative ChatGPT-authenticated websocket capture after a successful upgrade.
- `codex_transport_chatgpt_403.json`
  - Representative ChatGPT-authenticated upgrade rejection.
- `codex_transport_proxy_502.json`
  - Representative proxy or trust failure before websocket upgrade completion.

The success and failure fixtures model the stored `transport.json`
artifact shape rather than the live mitmproxy flow object. That keeps
diagnostics tests anchored to the persisted contract that operators and
future workers actually inspect.
