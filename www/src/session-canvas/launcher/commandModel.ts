// Pure command-center model: scopes, rows, and the actions a row triggers. No
// React, no stores — every builder is a deterministic function of its inputs so
// the row grammar and the four Agents states are unit-testable in isolation.

import type {
  HarnessName,
  RuntimeTemplateHarness,
  RuntimeTemplateSummary,
  RuntimeTemplateVendor,
} from "../../types";
import { CAPTURED_RUN_PROVIDERS, harnessLabel } from "../model/paneRecords";

export const LAUNCHER_SCOPES = [
  "root",
  "agents",
  "canvas",
  "workdir",
  "settings",
  "sessions",
] as const;
export type LauncherScope = (typeof LAUNCHER_SCOPES)[number];

/** Resolution status of the runtime-template fetch (drives the Agents states). */
export type AgentsStatus = "loading" | "error" | "empty" | "populated";

/** A leaf effect dispatched out to the canvas; scope nav is handled internally. */
export type LauncherCommand =
  | { kind: "spawn"; harness: HarnessName; runtimeTemplate?: string }
  | { kind: "reset-view" }
  | { kind: "focus-picker" }
  | { kind: "goto"; path: string }
  | { kind: "cycle-theme" }
  | { kind: "retry-agents" };

/** What a row does on `↵`: enter a sub-scope, or fire a leaf command. */
export type RowAction =
  | { kind: "enter"; scope: LauncherScope }
  | { kind: "command"; command: LauncherCommand };

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

const GROUP_AGENTS = "Agents";
const GROUP_CANVAS = "Canvas";
const GROUP_BROWSE = "Go to";

const VENDOR_LABELS: Record<RuntimeTemplateVendor, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
};

/** Captured-run harness a template launches under, or null if not spawnable here. */
export function templateSpawnHarness(template: RuntimeTemplateSummary): HarnessName | null {
  const recommended = template.recommended_model?.default?.harness ?? null;
  if (isCapturedRunHarness(recommended)) return recommended;
  // No spawnable recommendation: fall back to the first compatible vendor's
  // native harness (anthropic → claude, openai → codex) so the row stays usable.
  for (const vendor of template.vendors ?? []) {
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

/** Native rows (always present, always first) followed by specialist templates. */
export function buildAgentRows(
  templates: RuntimeTemplateSummary[],
  status: AgentsStatus,
): CommandRow[] {
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

  rows.push(...agentsStatusRows(status));
  return rows;
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
          title: "Couldn't load specialists",
          subtitle: "Native agents are still available",
          group: GROUP_AGENTS,
          disabled: true,
        },
        {
          value: "action:retry-agents",
          title: "Retry",
          subtitle: "Fetch the specialist fleet again",
          group: GROUP_AGENTS,
          action: { kind: "command", command: { kind: "retry-agents" } },
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

/** The re-homed canvas command-bar functions, now Canvas-domain entries. */
export function buildCanvasRows(themeName: string): CommandRow[] {
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
    {
      value: "cmd:cycle-theme",
      title: "Cycle theme",
      subtitle: `Current: ${themeName}`,
      group: GROUP_CANVAS,
      action: { kind: "command", command: { kind: "cycle-theme" } },
    },
  ];
}

/** Deferred scopes are wired in (enterable) but carry no internals this slice. */
const BROWSE_SCOPES: { scope: LauncherScope; title: string; subtitle: string }[] = [
  { scope: "workdir", title: "Workdir", subtitle: "Set where agents run" },
  { scope: "settings", title: "Settings", subtitle: "Homes, skills, defaults" },
  { scope: "sessions", title: "Sessions", subtitle: "Browse transcript history" },
];

function buildBrowseRows(): CommandRow[] {
  return BROWSE_SCOPES.map(({ scope, title, subtitle }) => ({
    value: `scope:${scope}`,
    title,
    subtitle,
    group: GROUP_BROWSE,
    trailing: "→",
    action: { kind: "enter", scope },
  }));
}

export interface ScopeRowInputs {
  templates: RuntimeTemplateSummary[];
  agentsStatus: AgentsStatus;
  themeName: string;
}

/** The full row set for a scope, in display order (grouped downstream). */
export function buildScopeRows(scope: LauncherScope, inputs: ScopeRowInputs): CommandRow[] {
  const { templates, agentsStatus, themeName } = inputs;
  switch (scope) {
    case "root":
      return [
        ...buildAgentRows(templates, agentsStatus),
        ...buildCanvasRows(themeName),
        ...buildBrowseRows(),
      ];
    case "agents":
      return buildAgentRows(templates, agentsStatus);
    case "canvas":
      return buildCanvasRows(themeName);
    case "workdir":
    case "settings":
    case "sessions":
      return [
        {
          value: `status:${scope}-deferred`,
          title: `${titleCase(scope)} is not in this slice yet`,
          subtitle: "Wired into the command center; internals land next",
          group: titleCase(scope),
          disabled: true,
        },
      ];
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

function titleCase(scope: LauncherScope): string {
  return scope.charAt(0).toUpperCase() + scope.slice(1);
}
