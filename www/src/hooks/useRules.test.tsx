import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CreateRuleBody } from "../types";
import { useRules } from "./useRules";

vi.mock("../api", () => ({
  fetchRules: vi.fn().mockResolvedValue([]),
  createRule: vi.fn().mockResolvedValue({
    id: "r1",
    name: "test",
    action: "strip_thinking",
    enabled: true,
    params: {},
    scope: { global: true, session_id: null, device_id: null, account_id: null, model: null },
    created_at: "2026-01-01T00:00:00Z",
    applied_count: 0,
  }),
  patchRule: vi.fn().mockResolvedValue({
    id: "r1",
    name: "test",
    action: "strip_thinking",
    enabled: false,
    params: {},
    scope: { global: true, session_id: null, device_id: null, account_id: null, model: null },
    created_at: "2026-01-01T00:00:00Z",
    applied_count: 0,
  }),
  deleteRule: vi.fn().mockResolvedValue(undefined),
}));

const TEST_RULE: CreateRuleBody = {
  name: "test",
  action: "strip_thinking",
  params: {},
  scope: { global: true, session_id: null, device_id: null, account_id: null, model: null },
};

describe("useRules — mutation invalidation", () => {
  let qc: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }

  async function setup() {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useRules(), { wrapper });
    await waitFor(() => expect(result.current.rules).toBeDefined());
    return { spy, result };
  }

  it("createRule invalidates [rules] on success", async () => {
    const { spy, result } = await setup();
    await act(async () => {
      await result.current.createRule(TEST_RULE);
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["rules"] });
  });

  it("toggleRule invalidates [rules] on success", async () => {
    const { spy, result } = await setup();
    await act(async () => {
      await result.current.toggleRule("r1", false);
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["rules"] });
  });

  it("deleteRule invalidates [rules] on success", async () => {
    const { spy, result } = await setup();
    await act(async () => {
      await result.current.deleteRule("r1");
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["rules"] });
  });
});
