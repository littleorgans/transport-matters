import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createApiTransport,
  createCapturedRun,
  deleteRun,
  fetchMeta,
  fetchTurnContent,
  listRuns,
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

describe("createCapturedRun", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("spawns a managed run via POST /api/runs and returns the run id", async () => {
    const fetchMock = stubFetch({ run: { runId: "run-abc123" } }, 201);

    await expect(createCapturedRun("claude")).resolves.toBe("run-abc123");

    expect(fetchMock).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cli: "claude" }),
    });
  });

  it("forwards an absolute cwd when supplied", async () => {
    const fetchMock = stubFetch({ run: { runId: "run-xyz" } }, 201);

    await expect(createCapturedRun("codex", "/work/proj")).resolves.toBe("run-xyz");

    expect(fetchMock).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cli: "codex", cwd: "/work/proj" }),
    });
  });

  it("throws on a non-OK spawn response", async () => {
    stubFetch({ detail: { code: "unsupported_cli", message: "no" } }, 400);

    await expect(createCapturedRun("claude")).rejects.toThrow("Failed to spawn captured run: 400");
  });
});

describe("deleteRun", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("stops a managed run via DELETE /api/runs/{id} with an encoded id", async () => {
    const fetchMock = stubFetch({ runId: "run/1", state: "exited", stopReason: "explicit-stop" });

    await deleteRun("run/1");

    expect(fetchMock).toHaveBeenCalledWith("/api/runs/run%2F1", { method: "DELETE" });
  });
});

describe("listRuns", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("lists managed runs via GET /api/runs and unwraps the runs array", async () => {
    const run = {
      runId: "run-1",
      cli: "claude",
      cwd: "/work/proj",
      storageDir: "/store/run-1",
      proxyPort: 4010,
      state: "running",
      viewerCount: 0,
      createdAt: "2026-06-09T00:00:00+00:00",
      startedAt: "2026-06-09T00:00:01+00:00",
      updatedAt: "2026-06-09T00:00:02+00:00",
      scrollbackBytes: 0,
      scrollbackLimitBytes: 1048576,
    };
    const fetchMock = stubFetch({ runs: [run] });

    await expect(listRuns()).resolves.toEqual([run]);
    expect(fetchMock).toHaveBeenCalledWith("/api/runs");
  });

  it("forwards cli, cwd, and state as query params when filtering", async () => {
    const fetchMock = stubFetch({ runs: [] });

    await listRuns({ cli: "codex", cwd: "/work/proj", state: "running" });

    expect(fetchMock).toHaveBeenCalledWith("/api/runs?cli=codex&cwd=%2Fwork%2Fproj&state=running");
  });

  it("throws on a non-OK list response", async () => {
    stubFetch({ detail: "boom" }, 500);

    await expect(listRuns()).rejects.toThrow("Failed to list captured runs: 500");
  });
});
