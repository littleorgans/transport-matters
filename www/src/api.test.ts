import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createApiTransport,
  fetchMeta,
  fetchTurnContent,
  resetApiTransport,
  setApiTransport,
} from "./api";

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("fetchTurnContent", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("fetches lazy turn content for an encoded exchange id", async () => {
    const body = {
      user_text: "show me the thing",
      response_text: "here it is",
      stop_reason: "end_turn",
    };
    const fetchMock = stubFetch(body);

    await expect(fetchTurnContent("exchange/id 1")).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledWith("/api/exchanges/exchange%2Fid%201/turn-content");
  });

  it("uses a configured base URL without changing endpoint callers", async () => {
    const body = {
      user_text: "show me the thing",
      response_text: "here it is",
      stop_reason: "end_turn",
    };
    const fetchMock = stubFetch(body);
    setApiTransport(createApiTransport({ baseUrl: "http://127.0.0.1:4321/" }));

    await expect(fetchTurnContent("exchange/id 1")).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:4321/api/exchanges/exchange%2Fid%201/turn-content",
    );
  });

  it("throws on non OK responses", async () => {
    stubFetch({ detail: "not found" }, 404);

    await expect(fetchTurnContent("missing")).rejects.toThrow(
      "Failed to fetch turn content for missing: 404",
    );
  });
});

describe("fetchMeta", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("keeps harness capability data separate from provider fields", async () => {
    const harnesses = [
      {
        id: "codex",
        display_name: "Codex",
        command_name: "codex",
        subcommand_id: "codex",
        binary_option: "--codex-bin",
        disable_flag: "--no-codex",
        proxy_mode: "explicit",
        trust_requirement: "codex_ca_certificate",
        shell_environment_policy: "sanitized_proxy_with_shell_excludes",
        pass_through_policy: "verbatim_after_separator",
        capabilities: {
          startup_probe: false,
          disposable_probe: false,
          overlay_before_work: false,
          tool_schema_overlay: true,
          provider_extras_controls: true,
          replay: false,
          fork: false,
          transport_diagnostics: true,
          codex_turn_telemetry: true,
          websocket_artifacts: true,
          http_fallback_artifacts: true,
        },
      },
    ];
    const fetchMock = stubFetch({
      cwd: "/tmp/workspace",
      harnesses,
      run_id: "run-123",
      workspace_id: "workspace/hash",
    });

    await expect(fetchMeta()).resolves.toEqual({
      cwd: "/tmp/workspace",
      harnesses,
      runId: "run-123",
      workspaceId: "workspace/hash",
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/meta");
  });
});
