import { describe, expect, it } from "vitest";
import type { RuntimeTemplateSummary } from "../../types";
import {
  buildAgentRows,
  buildScopeRows,
  filterRows,
  firstSelectableValue,
  groupRows,
  recommendedSubtitle,
  type ScopeRowInputs,
  templateSpawnHarness,
} from "./commandModel";

const research: RuntimeTemplateSummary = {
  name: "research",
  vendors: ["anthropic"],
  required_capabilities: [],
  recommended_model: {
    default: { harness: "claude", vendor: "anthropic" },
    by_vendor: { anthropic: { model: "Opus 4.8", effort: "xhigh" } },
  },
};

const codexSpec: RuntimeTemplateSummary = {
  name: "codex-spec",
  vendors: ["openai"],
  required_capabilities: [],
  recommended_model: {
    default: { harness: "codex", vendor: "openai" },
    by_vendor: { openai: { model: "GPT-5", effort: "high" } },
  },
};

// Recommends a harness the captured-run flow can't spawn, with no usable vendor.
const unsupported: RuntimeTemplateSummary = {
  name: "exotic",
  vendors: [],
  required_capabilities: [],
  recommended_model: { default: { harness: "pi", vendor: null } },
};

const baseInputs = (overrides: Partial<ScopeRowInputs> = {}): ScopeRowInputs => ({
  templates: [],
  agentsStatus: "populated",
  themeName: "none",
  ...overrides,
});

describe("templateSpawnHarness", () => {
  it("uses a captured-run recommendation directly", () => {
    expect(templateSpawnHarness(research)).toBe("claude");
    expect(templateSpawnHarness(codexSpec)).toBe("codex");
  });

  it("falls back to the first compatible vendor's native harness", () => {
    const noHarness: RuntimeTemplateSummary = { ...research, recommended_model: null };
    expect(templateSpawnHarness(noHarness)).toBe("claude");
    expect(templateSpawnHarness({ ...codexSpec, recommended_model: null })).toBe("codex");
  });

  it("returns null when nothing spawnable can be derived", () => {
    expect(templateSpawnHarness(unsupported)).toBeNull();
  });
});

describe("recommendedSubtitle", () => {
  it("joins model · effort · vendor from the recommendation", () => {
    expect(recommendedSubtitle(research)).toBe("Opus 4.8 · xhigh · Anthropic");
  });

  it("is undefined when no parts are available", () => {
    expect(
      recommendedSubtitle({ ...research, recommended_model: null, vendors: [] }),
    ).toBeUndefined();
  });
});

describe("buildAgentRows — Native is always present and first", () => {
  for (const status of ["loading", "error", "empty", "populated"] as const) {
    it(`keeps both native harnesses first in the ${status} state`, () => {
      const rows = buildAgentRows(status === "populated" ? [research] : [], status);
      expect(rows[0]?.value).toBe("agent:native:claude");
      expect(rows[1]?.value).toBe("agent:native:codex");
      expect(rows[0]?.action).toEqual({
        kind: "command",
        command: { kind: "spawn", harness: "claude" },
      });
    });
  }

  it("renders specialist rows that spawn with their template name", () => {
    const rows = buildAgentRows([research], "populated");
    const row = rows.find((candidate) => candidate.value === "agent:template:research");
    expect(row?.subtitle).toBe("Opus 4.8 · xhigh · Anthropic");
    expect(row?.action).toEqual({
      kind: "command",
      command: { kind: "spawn", harness: "claude", runtimeTemplate: "research" },
    });
  });

  it("disables a specialist row with no spawnable harness", () => {
    const rows = buildAgentRows([unsupported], "populated");
    const row = rows.find((candidate) => candidate.value === "agent:template:exotic");
    expect(row?.disabled).toBe(true);
    expect(row?.action).toBeUndefined();
  });

  it("loading shows native plus disabled skeletons", () => {
    const rows = buildAgentRows([], "loading");
    const skeletons = rows.filter((row) => row.value.startsWith("status:loading"));
    expect(skeletons).toHaveLength(2);
    expect(skeletons.every((row) => row.disabled)).toBe(true);
  });

  it("error shows native plus a retry action", () => {
    const rows = buildAgentRows([], "error");
    const retry = rows.find((row) => row.value === "action:retry-agents");
    expect(retry?.action).toEqual({ kind: "command", command: { kind: "retry-agents" } });
  });

  it("empty shows native plus a quiet install note and nothing spawnable beyond native", () => {
    const rows = buildAgentRows([], "empty");
    expect(rows.some((row) => row.value === "status:empty" && row.disabled)).toBe(true);
    const spawnable = rows.filter((row) => row.action?.kind === "command" && !row.disabled);
    expect(spawnable.map((row) => row.value)).toEqual([
      "agent:native:claude",
      "agent:native:codex",
    ]);
  });
});

describe("buildScopeRows", () => {
  it("root surfaces the Agents, Canvas, and Go-to groups", () => {
    const rows = buildScopeRows("root", baseInputs({ templates: [research] }));
    expect(new Set(rows.map((row) => row.group))).toEqual(new Set(["Agents", "Canvas", "Go to"]));
    expect(rows.some((row) => row.value === "cmd:cycle-theme")).toBe(true);
  });

  it("deferred scopes wire in as a single quiet placeholder", () => {
    const rows = buildScopeRows("workdir", baseInputs());
    expect(rows).toHaveLength(1);
    expect(rows[0]?.disabled).toBe(true);
    expect(rows[0]?.action).toBeUndefined();
  });
});

describe("row helpers", () => {
  it("filters across title and subtitle, case-insensitively", () => {
    const rows = buildScopeRows("agents", baseInputs({ templates: [codexSpec] }));
    const filtered = filterRows(rows, "gpt-5");
    expect(filtered.map((row) => row.value)).toEqual(["agent:template:codex-spec"]);
  });

  it("groups rows preserving first-seen order", () => {
    const groups = groupRows(buildScopeRows("root", baseInputs()));
    expect(groups.map(([label]) => label)).toEqual(["Agents", "Canvas", "Go to"]);
  });

  it("firstSelectableValue skips disabled rows", () => {
    const rows = buildAgentRows([], "loading");
    expect(firstSelectableValue(rows)).toBe("agent:native:claude");
  });
});
