// Pure command-center model: scopes, rows, and the actions a row triggers. No
// React, no stores — every builder is a deterministic function of its inputs so
// the row grammar and the four Agents states are unit-testable in isolation.

import {
  CANVAS_GESTURE_MODIFIERS,
  type CanvasGestureModifier,
} from "../../keybindings/gestureModifier";
import type {
  HarnessName,
  RuntimeTemplateHarness,
  RuntimeTemplateSummary,
  RuntimeTemplateVendor,
  SpaceSummary,
  WorktreeSummary,
} from "../../types";
import { CAPTURED_RUN_PROVIDERS, harnessLabel, locatorTail } from "../model/paneRecords";

export const LAUNCHER_SCOPES = [
  "root",
  "agents",
  "canvas",
  "workdir",
  "worktree",
  "settings",
  "sessions",
] as const;
export type LauncherScope = (typeof LAUNCHER_SCOPES)[number];

/** One level of the launcher navigation stack. The top frame is the live state. */
export interface NavFrame {
  scope: LauncherScope;
  query: string;
  highlightedValue?: string;
  /** Opaque scope argument (e.g. the spaceId a worktree sub-scope filters by). */
  param?: string;
}

export function topFrame(stack: NavFrame[]): NavFrame {
  const frame = stack.at(-1);
  if (!frame) throw new Error("Launcher navigation stack cannot be empty");
  return frame;
}

export function createScopeNavFrame(scope: LauncherScope, param?: string): NavFrame {
  return { scope, query: "", highlightedValue: undefined, param };
}

export function createRootNavFrame(): NavFrame {
  return createScopeNavFrame("root");
}

export function domainRowValue(scope: LauncherScope): string {
  return `domain:${scope}`;
}

export function pushFrame(
  stack: NavFrame[],
  target: LauncherScope,
  originValue: string,
  param?: string,
): NavFrame[] {
  const parent = { ...topFrame(stack), highlightedValue: originValue };
  return [...stack.slice(0, -1), parent, createScopeNavFrame(target, param)];
}

export function popFrame(stack: NavFrame[]): NavFrame[] {
  return stack.length > 1 ? stack.slice(0, -1) : stack;
}

export function updateTopFrame(stack: NavFrame[], patch: Partial<NavFrame>): NavFrame[] {
  return [...stack.slice(0, -1), { ...topFrame(stack), ...patch }];
}

/** Resolution status of the runtime-template fetch (drives the Agents states). */
export type AgentsStatus = "loading" | "error" | "empty" | "populated";

/** A leaf effect dispatched out to the canvas; scope nav is handled internally. */
export type LauncherCommand =
  | { kind: "spawn"; harness: HarnessName; runtimeTemplate?: string }
  | { kind: "reset-view" }
  | { kind: "focus-picker" }
  | { kind: "goto"; path: string }
  | { kind: "cycle-theme" }
  | { kind: "toggle-bypass-permissions" }
  | { kind: "set-canvas-gesture-modifier"; modifier: CanvasGestureModifier }
  | { kind: "select-worktree"; spaceId: string; worktreeId: string };

/** Command-center-local effects handled inside the launcher hook. */
export type LauncherEffect = "retry-agents";

/** What a row does on `↵`: enter a sub-scope, fire a command, or run a local effect. */
export type RowAction =
  | { kind: "enter"; scope: LauncherScope; param?: string }
  | { kind: "command"; command: LauncherCommand }
  | { kind: "effect"; effect: LauncherEffect };

/** What a single gesture does to the palette. */
export type Lifecycle = "descend" | "run-close" | "run-stay" | "commit-close" | "none";

/** Per-action key bindings. Enter/click reads `enter`; ArrowRight reads `advance`. */
export interface Interaction {
  enter: Lifecycle;
  advance: Lifecycle;
}

const SCOPE_INTERACTION: Interaction = { enter: "descend", advance: "descend" };
const RUN_AND_CLOSE: Interaction = { enter: "run-close", advance: "none" };
const COMMAND_INTERACTIONS: Partial<Record<LauncherCommand["kind"], Interaction>> = {
  "cycle-theme": { enter: "commit-close", advance: "run-stay" },
  // Single in-place toggle: → flips on/off and keeps the palette open; ↵ closes.
  "toggle-bypass-permissions": { enter: "commit-close", advance: "run-stay" },
};
const EFFECT_INTERACTIONS: Record<LauncherEffect, Interaction> = {
  "retry-agents": { enter: "run-stay", advance: "none" },
};

export function interactionFor(action: RowAction): Interaction {
  switch (action.kind) {
    case "enter":
      return SCOPE_INTERACTION;
    case "command":
      return COMMAND_INTERACTIONS[action.command.kind] ?? RUN_AND_CLOSE;
    case "effect":
      return EFFECT_INTERACTIONS[action.effect];
  }
}

export interface CommandRow {
  /** Stable, unique id; also the combobox item value. */
  value: string;
  title: string;
  subtitle?: string;
  /** Group heading the row sorts under. */
  group: string;
  /** Agent-coloured rows seed their rail from this id (see agentPalette). */
  railSeed?: string;
  /** Trailing accelerator hint, e.g. "⌘A". */
  trailing?: string;
  /** Status/skeleton rows are inert (not highlightable, no action). */
  disabled?: boolean;
  action?: RowAction;
}

const GROUP_DOMAINS = "Domains";
const GROUP_AGENTS = "Agents";
const GROUP_CANVAS = "Canvas";
const GROUP_SETTINGS = "Settings";
const GROUP_WORKDIR = "Workdir";

const VENDOR_LABELS: Record<RuntimeTemplateVendor, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
};

/** Captured-run harness a template launches under, or null if not spawnable here. */
export function templateSpawnHarness(template: RuntimeTemplateSummary): HarnessName | null {
  const recommended = template.recommended_model?.default?.harness ?? null;
  if (isCapturedRunHarness(recommended)) return recommended;
  // No spawnable harness recommendation: derive the native harness from the
  // recommended VENDOR first (anthropic → claude, openai → codex), then any
  // compatible vendor. Consulting default.vendor before vendors[] keeps the
  // spawn target consistent with the subtitle (see recommendedSubtitle) instead
  // of silently launching vendors[0].
  const recommendedVendor = template.recommended_model?.default?.vendor ?? null;
  for (const vendor of [recommendedVendor, ...(template.vendors ?? [])]) {
    if (!vendor) continue;
    const harness = vendorNativeHarness(vendor);
    if (harness) return harness;
  }
  return null;
}

/** Subtitle = the recommended target (`<Model> · <effort> · <Vendor>`). */
export function recommendedSubtitle(template: RuntimeTemplateSummary): string | undefined {
  const recommended = template.recommended_model;
  const vendor = recommended?.default?.vendor ?? template.vendors?.[0] ?? null;
  const perVendor = vendor ? recommended?.by_vendor?.[vendor] : undefined;
  const parts = [
    perVendor?.model,
    perVendor?.effort,
    vendor ? VENDOR_LABELS[vendor] : undefined,
  ].filter((part): part is string => typeof part === "string" && part.length > 0);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/** The spawnable agent rows: native (always present, always first) then specialists. */
function agentSpawnRows(templates: RuntimeTemplateSummary[]): CommandRow[] {
  const rows: CommandRow[] = CAPTURED_RUN_PROVIDERS.map((harness) => ({
    value: `agent:native:${harness}`,
    title: harnessLabel(harness),
    subtitle: "Native",
    group: GROUP_AGENTS,
    railSeed: `native:${harness}`,
    action: { kind: "command", command: { kind: "spawn", harness } },
  }));

  for (const template of templates) {
    const harness = templateSpawnHarness(template);
    rows.push({
      value: `agent:template:${template.name}`,
      title: template.name,
      subtitle:
        recommendedSubtitle(template) ?? (harness ? harnessLabel(harness) : "Unavailable harness"),
      group: GROUP_AGENTS,
      railSeed: `template:${template.name}`,
      disabled: harness === null,
      action:
        harness === null
          ? undefined
          : {
              kind: "command",
              command: { kind: "spawn", harness, runtimeTemplate: template.name },
            },
    });
  }
  return rows;
}

/** Agents-scope rows: the spawnable rows plus the quiet four-state status rows. */
export function buildAgentRows(
  templates: RuntimeTemplateSummary[],
  status: AgentsStatus,
): CommandRow[] {
  return [...agentSpawnRows(templates), ...agentsStatusRows(status)];
}

/** The quiet status/skeleton/retry rows that make the four states legible. */
function agentsStatusRows(status: AgentsStatus): CommandRow[] {
  switch (status) {
    case "loading":
      return [0, 1].map((index) => ({
        value: `status:loading:${index}`,
        title: "Loading specialists…",
        group: GROUP_AGENTS,
        disabled: true,
      }));
    case "error":
      return [
        {
          value: "status:error",
          title: "Couldn’t load specialists",
          subtitle: "Native agents are still available",
          group: GROUP_AGENTS,
          disabled: true,
        },
        {
          value: "action:retry-agents",
          title: "Retry",
          subtitle: "Fetch the specialist fleet again",
          group: GROUP_AGENTS,
          action: { kind: "effect", effect: "retry-agents" },
        },
      ];
    case "empty":
      return [
        {
          value: "status:empty",
          title: "Install a fleet to add specialists",
          subtitle: "Native agents are always available",
          group: GROUP_AGENTS,
          disabled: true,
        },
      ];
    case "populated":
      return [];
  }
}

/** The re-homed canvas command-bar functions, now the Canvas-domain entries. */
export function buildCanvasRows(): CommandRow[] {
  return [
    {
      value: "cmd:reset-view",
      title: "Reset view",
      subtitle: "Recentre and unzoom the canvas",
      group: GROUP_CANVAS,
      action: { kind: "command", command: { kind: "reset-view" } },
    },
    {
      value: "cmd:focus-picker",
      title: "Focus picker",
      subtitle: "Jump to the session picker pane",
      group: GROUP_CANVAS,
      action: { kind: "command", command: { kind: "focus-picker" } },
    },
    {
      value: "cmd:goto-lab",
      title: "Go to Lab",
      subtitle: "Open the canvas lab surface",
      group: GROUP_CANVAS,
      action: { kind: "command", command: { kind: "goto", path: "/canvas-lab" } },
    },
  ];
}

/** Settings-domain entries. Theme plus the single configurable canvas gesture. */
export function buildSettingsRows(
  themeName: string,
  canvasGestureModifier: CanvasGestureModifier,
  bypassPermissions: boolean,
): CommandRow[] {
  return [
    {
      value: "cmd:cycle-theme",
      title: "Cycle theme",
      subtitle: `Current: ${themeName}`,
      group: GROUP_SETTINGS,
      action: { kind: "command", command: { kind: "cycle-theme" } },
    },
    {
      value: "settings:bypass-permissions",
      title: "Bypass all permission checks",
      subtitle: bypassPermissions
        ? "On — spawned agents skip permission prompts"
        : "Off — spawned agents prompt for permissions",
      group: GROUP_SETTINGS,
      trailing: bypassPermissions ? "On" : "Off",
      action: { kind: "command", command: { kind: "toggle-bypass-permissions" } },
    },
    ...CANVAS_GESTURE_MODIFIERS.map((modifier): CommandRow => {
      const selected = modifier === canvasGestureModifier;
      return {
        value: `settings:canvas-gesture-modifier:${modifier}`,
        title: `Canvas gesture modifier: ${modifier}`,
        subtitle: selected
          ? "Current modifier for drag pan and wheel zoom"
          : `Use ${modifier} for canvas drag pan and wheel zoom`,
        group: GROUP_SETTINGS,
        trailing: selected ? "Current" : undefined,
        action: {
          kind: "command",
          command: { kind: "set-canvas-gesture-modifier", modifier },
        },
      };
    }),
  ];
}

/** Subtitle for a worktree row: its root path. */
function worktreeSubtitle(worktree: WorktreeSummary): string {
  return worktree.path;
}

/** Title for a worktree row: the branch, else "main worktree", else the path tail. */
function worktreeTitle(worktree: WorktreeSummary): string {
  if (worktree.branch) return worktree.branch;
  return worktree.isPrimary ? "main worktree" : locatorTail(worktree.path);
}

/**
 * Workdir scope: one row per detected Space (R7). Rows are titled by the project
 * label (never the bare word "Space"), so they never read like the Settings
 * "Canvas gesture modifier: Space" row. A single-worktree Space selects its lone
 * worktree directly; a multi-worktree Space descends into the worktree sub-scope.
 */
export function buildSpaceRows(
  spaces: SpaceSummary[],
  activeWorktreeId: string | null,
): CommandRow[] {
  if (spaces.length === 0) {
    return [
      {
        value: "status:workdir-empty",
        title: "No spaces detected yet",
        subtitle: "Open a project directory to capture a Space",
        group: GROUP_WORKDIR,
        disabled: true,
      },
    ];
  }
  return spaces.map((space): CommandRow => {
    const single = space.worktrees.length === 1 ? space.worktrees[0] : undefined;
    const rooted = single && single.worktreeId === activeWorktreeId;
    return {
      value: `space:${space.spaceId}`,
      title: space.label,
      subtitle: single ? worktreeSubtitle(single) : `${space.worktrees.length} worktrees`,
      group: GROUP_WORKDIR,
      trailing: rooted ? "Current" : space.kind === "repo" ? "repo" : "dir",
      action: single
        ? {
            kind: "command",
            command: {
              kind: "select-worktree",
              spaceId: space.spaceId,
              worktreeId: single.worktreeId,
            },
          }
        : { kind: "enter", scope: "worktree", param: space.spaceId },
    };
  });
}

/** Worktree sub-scope: one row per worktree of the Space named by `spaceId` (the nav param). */
export function buildWorktreeRows(
  spaces: SpaceSummary[],
  spaceId: string | undefined,
  activeWorktreeId: string | null,
): CommandRow[] {
  const space = spaces.find((candidate) => candidate.spaceId === spaceId);
  if (!space) {
    return [
      {
        value: "status:worktree-missing",
        title: "Space no longer available",
        group: GROUP_WORKDIR,
        disabled: true,
      },
    ];
  }
  return space.worktrees.map(
    (worktree): CommandRow => ({
      value: `worktree:${worktree.worktreeId}`,
      title: worktreeTitle(worktree),
      subtitle: worktreeSubtitle(worktree),
      group: GROUP_WORKDIR,
      trailing:
        worktree.worktreeId === activeWorktreeId
          ? "Current"
          : worktree.missing
            ? "Missing"
            : undefined,
      disabled: worktree.missing,
      action: worktree.missing
        ? undefined
        : {
            kind: "command",
            command: {
              kind: "select-worktree",
              spaceId: space.spaceId,
              worktreeId: worktree.worktreeId,
            },
          },
    }),
  );
}

/** The five root domains. Each ↵ ENTERS its scope; accelerators jump from anywhere. */
const DOMAINS: {
  scope: LauncherScope;
  title: string;
  subtitle: string;
  accelerator?: string;
}[] = [
  { scope: "agents", title: "Agents", subtitle: "spawn & configure runs", accelerator: "⌘A" },
  { scope: "canvas", title: "Canvas", subtitle: "panes · layout · navigation" },
  { scope: "workdir", title: "Workdir", subtitle: "set where agents run" },
  {
    scope: "settings",
    title: "Settings",
    subtitle: "homes · skills · defaults",
    accelerator: "⌘,",
  },
  { scope: "sessions", title: "Sessions", subtitle: "browse transcript history" },
];

/** Number of root domains, shown as the "{n} domains" count. */
export const LAUNCHER_DOMAIN_COUNT = DOMAINS.length;

function buildDomainRows(): CommandRow[] {
  return DOMAINS.map(({ scope, title, subtitle, accelerator }) => ({
    value: domainRowValue(scope),
    title,
    subtitle,
    group: GROUP_DOMAINS,
    trailing: accelerator,
    action: { kind: "enter", scope },
  }));
}

/** Flat search set: every spawnable agent and re-homed command, grouped by domain. */
function buildFlatSearchRows(inputs: ScopeRowInputs): CommandRow[] {
  return [
    ...agentSpawnRows(inputs.templates),
    ...buildCanvasRows(),
    ...buildSettingsRows(inputs.themeName, inputs.canvasGestureModifier, inputs.bypassPermissions),
  ];
}

/** A single quiet placeholder for a domain whose internals are not wired yet. */
function buildDeferredRows(label: string): CommandRow[] {
  return [
    {
      value: `status:${label.toLowerCase()}-deferred`,
      title: `${label} lands next`,
      subtitle: "Wired into the command center; internals to come",
      group: label,
      disabled: true,
    },
  ];
}

export interface ScopeRowInputs {
  templates: RuntimeTemplateSummary[];
  agentsStatus: AgentsStatus;
  themeName: string;
  canvasGestureModifier: CanvasGestureModifier;
  bypassPermissions: boolean;
  spaces: SpaceSummary[];
  activeWorktreeId: string | null;
}

/**
 * The full row set for a scope, in display order (grouped downstream). Root is
 * domains-first: an empty query lists the five enterable domains; any query
 * flat-searches every agent and command across domains (the Raycast model).
 */
export function buildScopeRows(
  scope: LauncherScope,
  inputs: ScopeRowInputs,
  query: string,
  param?: string,
): CommandRow[] {
  const { templates, agentsStatus, themeName, canvasGestureModifier, bypassPermissions } = inputs;
  switch (scope) {
    case "root":
      return query.trim().length === 0 ? buildDomainRows() : buildFlatSearchRows(inputs);
    case "agents":
      return buildAgentRows(templates, agentsStatus);
    case "canvas":
      return buildCanvasRows();
    case "settings":
      return buildSettingsRows(themeName, canvasGestureModifier, bypassPermissions);
    case "workdir":
      return buildSpaceRows(inputs.spaces, inputs.activeWorktreeId);
    case "worktree":
      return buildWorktreeRows(inputs.spaces, param, inputs.activeWorktreeId);
    case "sessions":
      return buildDeferredRows("Sessions");
  }
}

/** Case-insensitive substring filter over title + subtitle. Empty query = all. */
export function filterRows(rows: CommandRow[], query: string): CommandRow[] {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) return rows;
  return rows.filter((row) => {
    const haystack = `${row.title} ${row.subtitle ?? ""}`.toLowerCase();
    return haystack.includes(needle);
  });
}

/** First highlightable (non-disabled) row's value, for auto-highlight on open. */
export function firstSelectableValue(rows: CommandRow[]): string | undefined {
  return rows.find((row) => !row.disabled)?.value;
}

/** Group rows by their `group` label, preserving first-seen group order. */
export function groupRows(rows: CommandRow[]): [string, CommandRow[]][] {
  const order: string[] = [];
  const byGroup = new Map<string, CommandRow[]>();
  for (const row of rows) {
    const bucket = byGroup.get(row.group);
    if (bucket) {
      bucket.push(row);
    } else {
      order.push(row.group);
      byGroup.set(row.group, [row]);
    }
  }
  return order.map((group) => [group, byGroup.get(group) ?? []]);
}

function isCapturedRunHarness(value: RuntimeTemplateHarness | null): value is HarnessName {
  return value === "claude" || value === "codex";
}

function vendorNativeHarness(vendor: RuntimeTemplateVendor): HarnessName | null {
  if (vendor === "anthropic") return "claude";
  if (vendor === "openai") return "codex";
  return null;
}
