# Lessons

- Before advising on install commands, inspect the repo recipes and separate dependency setup, editable local tool installs, and published release installs.
- For Helioy product strategy, treat `transport-matters`, `runtime-matters`, and `context-matters` as standalone offerings that integrate through a shared journey and protocol. Do not frame one as the next evolution of another.
- Treat `littleorgans` as the main integrated product experience that packages standalone Helioy offerings into a beautiful desktop app. Individual products can still have their own Electron apps, CLIs, docs, and release tracks.
- For Transport Matters UX, do not anchor new designs around the existing ARM breakpoint workflow. Prefer staged launch and overlay workflows: capture startup payload, edit or save overlay, then run the working agent session through that overlay.
- In the Transport Matters staged launch UX, include Screen 0 for env vars before probe capture because env vars can affect the initial payload. Include a separate exchange detail screen after the working session for inspection tools.
- In Transport Matters architecture language, distinguish agent harnesses or clients from upstream providers. Claude Code, Codex, Gemini CLI, OpenCode, and similar CLIs are harnesses or clients. Anthropic, OpenAI, Google, and similar APIs are providers.
- Classify the harness driver boundary and capability surface work as a feature for PR titles and release notes, even when the final patch also includes install or metadata hygiene.
