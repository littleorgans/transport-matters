import { describe, expect, it } from "vitest";
import type { RuntimeTemplateSummary } from "../../types";
import {
  buildAgentRows,
  buildScopeRows,
  createRootNavFrame,
  domainRowValue,
  filterRows,
  firstSelectableValue,
  groupRows,
  type Interaction,
  interactionFor,
  type LauncherCommand,
  popFrame,
  pushFrame,
  type RowAction,
  recommendedSubtitle,
  type ScopeRowInputs,
  templateSpawnHarness,
  topFrame,
  updateTopFrame,
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

// default.harness is absent but default.vendor (openai) names a captured-run
// vendor; vendors[0] is a DIFFERENT vendor (anthropic). The spawn must follow
// the recommended vendor, not vendors[0].
const vendorMismatch: RuntimeTemplateSummary = {
  name: "vendor-mismatch",
  vendors: ["anthropic", "openai"],
  required_capabilities: [],
  recommended_model: {
    default: { vendor: "openai" },
    by_vendor: { openai: { model: "GPT-5", effort: "high" } },
  },
};

const baseInputs = (overrides: Partial<ScopeRowInputs> = {}): ScopeRowInputs => ({
  templates: [],
  agentsStatus: "populated",
  themeName: "NONE",
  canvasGestureModifier: "Shift",
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

  it("prefers the recommended vendor's native harness over vendors[0]", () => {
    // default.vendor=openai with no default.harness must spawn codex, even though
    // vendors[0] is anthropic. Regression guard against vendors[0] winning.
    expect(templateSpawnHarness(vendorMismatch)).toBe("codex");
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

  it("spawns a specialist under its recommended vendor's harness, not vendors[0]", () => {
    const rows = buildAgentRows([vendorMismatch], "populated");
    const row = rows.find((candidate) => candidate.value === "agent:template:vendor-mismatch");
    expect(row?.disabled).toBeFalsy();
    expect(row?.action).toEqual({
      kind: "command",
      command: { kind: "spawn", harness: "codex", runtimeTemplate: "vendor-mismatch" },
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
    expect(retry?.action).toEqual({ kind: "effect", effect: "retry-agents" });
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

describe("interactionFor", () => {
  const runAndClose: Interaction = { enter: "run-close", advance: "none" };
  const commitCycleTheme: Interaction = { enter: "commit-close", advance: "run-stay" };
  const commandCases: [LauncherCommand, Interaction][] = [
    [{ kind: "spawn", harness: "claude" }, runAndClose],
    [{ kind: "reset-view" }, runAndClose],
    [{ kind: "focus-picker" }, runAndClose],
    [{ kind: "goto", path: "/canvas-lab" }, runAndClose],
    [{ kind: "cycle-theme" }, commitCycleTheme],
    [{ kind: "set-canvas-gesture-modifier", modifier: "Shift" }, runAndClose],
  ];
  const actionCases: [string, RowAction, Interaction][] = [
    ["enter scope", { kind: "enter", scope: "agents" }, { enter: "descend", advance: "descend" }],
    ...commandCases.map(([command, expected]): [string, RowAction, Interaction] => [
      `command ${command.kind}`,
      { kind: "command", command },
      expected,
    ]),
    [
      "retry effect",
      { kind: "effect", effect: "retry-agents" },
      { enter: "run-stay", advance: "none" },
    ],
  ];

  for (const [name, action, expected] of actionCases) {
    it(`maps ${name} to its gesture lifecycle`, () => {
      expect(interactionFor(action)).toEqual(expected);
    });
  }
});

describe("NavFrame stack", () => {
  it("pushFrame stamps the parent origin and creates a clean child frame", () => {
    const stack = updateTopFrame([createRootNavFrame()], {
      query: "set",
      highlightedValue: domainRowValue("settings"),
    });

    const next = pushFrame(stack, "settings", domainRowValue("settings"));

    expect(next).toEqual([
      { scope: "root", query: "set", highlightedValue: "domain:settings" },
      { scope: "settings", query: "", highlightedValue: undefined },
    ]);
  });

  it("popFrame preserves the revealed frame state and stops at the base frame", () => {
    const root = updateTopFrame([createRootNavFrame()], {
      query: "can",
      highlightedValue: domainRowValue("canvas"),
    });
    const child = updateTopFrame(pushFrame(root, "canvas", domainRowValue("canvas")), {
      query: "reset",
      highlightedValue: "cmd:reset-view",
    });

    expect(popFrame(child)).toEqual(root);
    expect(popFrame(root)).toBe(root);
  });

  it("updateTopFrame only patches the live frame", () => {
    const stack = pushFrame([createRootNavFrame()], "settings", domainRowValue("settings"));

    expect(updateTopFrame(stack, { query: "theme" })).toEqual([
      { scope: "root", query: "", highlightedValue: "domain:settings" },
      { scope: "settings", query: "theme", highlightedValue: undefined },
    ]);
  });

  it("supports future deeper navigation by popping one frame at a time", () => {
    const first = pushFrame([createRootNavFrame()], "settings", domainRowValue("settings"));
    const second = pushFrame(first, "canvas", "cmd:future-enter-canvas");

    expect(topFrame(second).scope).toBe("canvas");
    const backToSettings = popFrame(second);
    expect(topFrame(backToSettings).scope).toBe("settings");
    expect(topFrame(backToSettings).highlightedValue).toBe("cmd:future-enter-canvas");
    expect(popFrame(backToSettings)).toEqual([
      { scope: "root", query: "", highlightedValue: "domain:settings" },
    ]);
  });
});

describe("buildScopeRows — domains-first root", () => {
  it("an empty query lists the five enterable domains (agents collapsed)", () => {
    const rows = buildScopeRows("root", baseInputs({ templates: [research] }), "");
    expect(rows.map((row) => row.value)).toEqual([
      "domain:agents",
      "domain:canvas",
      "domain:workdir",
      "domain:settings",
      "domain:sessions",
    ]);
    expect(new Set(rows.map((row) => row.group))).toEqual(new Set(["Domains"]));
    // Every domain enters its scope; no agent rows spill at root.
    expect(rows.every((row) => row.action?.kind === "enter")).toBe(true);
    expect(rows.some((row) => row.value.startsWith("agent:"))).toBe(false);
  });

  it("Agents and Settings domains carry their accelerators", () => {
    const rows = buildScopeRows("root", baseInputs(), "");
    expect(rows.find((row) => row.value === "domain:agents")?.trailing).toBe("⌘A");
    expect(rows.find((row) => row.value === "domain:settings")?.trailing).toBe("⌘,");
    expect(rows.find((row) => row.value === "domain:canvas")?.trailing).toBeUndefined();
  });

  it("a non-empty query flat-searches agents AND commands across domains", () => {
    const inputs = baseInputs({ templates: [research] });
    const rows = buildScopeRows("root", inputs, "research");
    // The whole flat set is returned (filtering happens downstream); it carries
    // both agent rows and re-homed commands, and no domain entries.
    expect(rows.some((row) => row.value === "agent:template:research")).toBe(true);
    expect(rows.some((row) => row.value === "cmd:reset-view")).toBe(true);
    expect(rows.some((row) => row.value === "cmd:cycle-theme")).toBe(true);
    expect(rows.some((row) => row.value.startsWith("domain:"))).toBe(false);
    // Filtering the flat set from cold still finds the native agents.
    expect(
      filterRows(buildScopeRows("root", baseInputs(), "claude"), "claude").map((r) => r.value),
    ).toContain("agent:native:claude");
  });

  it("Settings scope carries Theme and the current canvas gesture modifier", () => {
    const rows = buildScopeRows("settings", baseInputs(), "");
    expect(rows.map((row) => row.value)).toEqual([
      "cmd:cycle-theme",
      "settings:canvas-gesture-modifier:Shift",
      "settings:canvas-gesture-modifier:Space",
    ]);
    expect(rows.find((row) => row.value === "cmd:cycle-theme")?.subtitle).toBe("Current: NONE");
    expect(rows.find((row) => row.value.endsWith(":Shift"))?.trailing).toBe("Current");
    expect(rows.find((row) => row.value.endsWith(":Space"))?.action).toEqual({
      kind: "command",
      command: { kind: "set-canvas-gesture-modifier", modifier: "Space" },
    });
  });

  it("Settings scope reflects Space as the current canvas gesture modifier", () => {
    const rows = buildScopeRows("settings", baseInputs({ canvasGestureModifier: "Space" }), "");
    expect(rows.find((row) => row.value.endsWith(":Shift"))?.trailing).toBeUndefined();
    expect(rows.find((row) => row.value.endsWith(":Space"))?.trailing).toBe("Current");
  });

  it("Canvas scope drops Theme (moved to Settings)", () => {
    const rows = buildScopeRows("canvas", baseInputs(), "");
    expect(rows.map((row) => row.value)).toEqual([
      "cmd:reset-view",
      "cmd:focus-picker",
      "cmd:goto-lab",
    ]);
  });

  it("Workdir/Sessions wire in as a single quiet placeholder", () => {
    for (const scope of ["workdir", "sessions"] as const) {
      const rows = buildScopeRows(scope, baseInputs(), "");
      expect(rows).toHaveLength(1);
      expect(rows[0]?.disabled).toBe(true);
      expect(rows[0]?.action).toBeUndefined();
    }
  });
});

describe("row helpers", () => {
  it("filters across title and subtitle, case-insensitively", () => {
    const rows = buildScopeRows("agents", baseInputs({ templates: [codexSpec] }), "");
    const filtered = filterRows(rows, "gpt-5");
    expect(filtered.map((row) => row.value)).toEqual(["agent:template:codex-spec"]);
  });

  it("groups the domains root under a single Domains heading", () => {
    const groups = groupRows(buildScopeRows("root", baseInputs(), ""));
    expect(groups.map(([label]) => label)).toEqual(["Domains"]);
  });

  it("firstSelectableValue skips disabled rows", () => {
    const rows = buildAgentRows([], "loading");
    expect(firstSelectableValue(rows)).toBe("agent:native:claude");
  });
});
