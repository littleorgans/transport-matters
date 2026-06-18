import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createApiTransport,
  createCapturedRun,
  fetchMeta,
  fetchRuntimeTemplates,
  fetchTurnContent,
  listRuns,
  resetApiTransport,
  setApiTransport,
  terminateRun,
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

    await expect(fetchTurnContent("run-current", "exchange/id 1")).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/runs/run-current/exchanges/exchange%2Fid%201/turn-content",
    );
  });

  it("uses a configured base URL without changing endpoint callers", async () => {
    const body = {
      user_text: "show me the thing",
      response_text: "here it is",
      stop_reason: "end_turn",
    };
    const fetchMock = stubFetch(body);
    setApiTransport(createApiTransport({ baseUrl: "http://127.0.0.1:4321/" }));

    await expect(fetchTurnContent("run-current", "exchange/id 1")).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:4321/v1/runs/run-current/exchanges/exchange%2Fid%201/turn-content",
    );
  });

  it("throws on non OK responses", async () => {
    stubFetch({ detail: "not found" }, 404);

    await expect(fetchTurnContent("run-current", "missing")).rejects.toThrow(
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

describe("createCapturedRun", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("spawns a managed run via POST /v1/runs and returns the run id", async () => {
    const fetchMock = stubFetch({ run: { runId: "run-abc123" } }, 201);

    await expect(createCapturedRun("claude")).resolves.toBe("run-abc123");

    expect(fetchMock).toHaveBeenCalledWith("/v1/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ harness: "claude", oscColorReplies: true }),
    });
  });

  it("forwards an absolute cwd when supplied", async () => {
    const fetchMock = stubFetch({ run: { runId: "run-xyz" } }, 201);

    await expect(createCapturedRun("codex", "/work/proj")).resolves.toBe("run-xyz");

    expect(fetchMock).toHaveBeenCalledWith("/v1/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ harness: "codex", cwd: "/work/proj", oscColorReplies: true }),
    });
  });

  it("threads a runtime template into the POST body (recommended-target launch)", async () => {
    const fetchMock = stubFetch({ run: { runId: "run-tpl" } }, 201);

    await expect(createCapturedRun("claude", undefined, true, "research")).resolves.toBe("run-tpl");

    expect(fetchMock).toHaveBeenCalledWith("/v1/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        harness: "claude",
        oscColorReplies: true,
        runtimeTemplate: "research",
      }),
    });
  });

  it("throws on a non-OK spawn response", async () => {
    stubFetch({ detail: { code: "unsupported_harness", message: "no" } }, 400);

    await expect(createCapturedRun("claude")).rejects.toThrow("Failed to spawn captured run: 400");
  });
});

describe("fetchRuntimeTemplates", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("returns the items from GET /v1/runtime-templates", async () => {
    const items = [
      {
        name: "research",
        vendors: ["anthropic"],
        required_capabilities: [],
        recommended_model: null,
      },
    ];
    const fetchMock = stubFetch({ items });

    await expect(fetchRuntimeTemplates()).resolves.toEqual(items);

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/v1/runtime-templates");
  });

  it("throws on a non-OK response so the launcher can degrade to Native-only", async () => {
    stubFetch({}, 500);

    await expect(fetchRuntimeTemplates()).rejects.toThrow("Failed to load runtime templates: 500");
  });
});

describe("terminateRun", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("terminates a managed run via POST /v1/runs/{id}/terminate with an encoded id", async () => {
    const fetchMock = stubFetch({
      run: { runId: "run/1", state: "TERMINATED", endReason: "explicit" },
    });

    await terminateRun("run/1");

    expect(fetchMock).toHaveBeenCalledWith("/v1/runs/run%2F1/terminate", { method: "POST" });
  });
});

describe("listRuns", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("lists managed runs via GET /v1/runs and unwraps the items array", async () => {
    const run = {
      runId: "run-1",
      workspaceId: "workspace/hash",
      sessionId: "session-1",
      harness: "claude",
      state: "RUNNING",
      createdAt: "2026-06-09T00:00:00+00:00",
    };
    const fetchMock = stubFetch({ items: [run], nextCursor: null });

    await expect(listRuns()).resolves.toEqual([run]);
    expect(fetchMock).toHaveBeenCalledWith("/v1/runs");
  });

  it("forwards state as a query param when filtering", async () => {
    const fetchMock = stubFetch({ items: [], nextCursor: null });

    await listRuns({ state: "RUNNING" });

    expect(fetchMock).toHaveBeenCalledWith("/v1/runs?state=RUNNING");
  });

  it("throws on a non-OK list response", async () => {
    stubFetch({ detail: "boom" }, 500);

    await expect(listRuns()).rejects.toThrow("Failed to list captured runs: 500");
  });
});
