import type { ToolDef } from "@tm/core/types/ir";
import type { Override } from "@tm/core/types/overrides";
import { useEffect, useMemo, useState } from "react";
import { useEditableOverride } from "../../hooks/useEditableOverride";
import { toolChars } from "../../lib/charAccounting";
import { hasOverride, overrideValue } from "../../lib/overrides";
import { toolTarget } from "../../lib/overrideTargets";
import { SizeDelta } from "../detail/atoms";
import { Toggle } from "../Toggle";
import { noopOverride, overrideCountLabel } from "./overrideUtils";
import { TextOverrideEditor } from "./TextOverrideEditor";

interface ToolsSectionProps {
  tools: ToolDef[];
  overrides?: Override[];
  onOverride?: (batch: Override[]) => void;
  /**
   * Read-only mode: synthesized overrides drive the display but the
   * bulk-control cluster, per-group all/none, and per-tool toggles are
   * hidden. Used by the Inspect tab.
   */
  readOnly?: boolean;
  /** Start tool groups and rows expanded for fullscreen export serialization. */
  expandAll?: boolean;
}

interface EditorToolGroup {
  prefix: string;
  tools: ToolDef[];
  totalChars: number;
}

function pluginLabel(name: string): string {
  if (!name.startsWith("mcp__")) return "built-in";
  const parts = name.split("__");
  return (parts[1] ?? "").replace(/^plugin_/, "");
}

function groupTools<T extends { name: string }>(tools: T[]): [string, T[]][] {
  const map: Record<string, T[]> = {};
  for (const t of tools) {
    const group = pluginLabel(t.name);
    if (!map[group]) map[group] = [];
    map[group].push(t);
  }
  return Object.entries(map).sort(([a], [b]) => {
    if (a === "built-in") return -1;
    if (b === "built-in") return 1;
    return a.localeCompare(b);
  });
}

function displayName(name: string): string {
  const idx = name.indexOf("__");
  return idx >= 0 ? name.slice(idx + 2) : name;
}

function buildEditorGroups(tools: ToolDef[]): EditorToolGroup[] {
  return groupTools(tools).map(([prefix, items]) => {
    const sorted = [...items].sort((a, b) => b.description.length - a.description.length);
    return {
      prefix,
      tools: sorted,
      totalChars: sorted.reduce((sum, t) => sum + toolChars(t), 0),
    };
  });
}

function bulkToggle(
  tools: ToolDef[],
  overrides: Override[],
  value: boolean | null,
  include: (tool: ToolDef) => boolean = () => true,
): Override[] {
  return tools
    .filter((tool) => {
      if (!include(tool)) return false;
      const current = overrideValue<boolean>(overrides, "tool_toggle", toolTarget(tool.name));
      return value === null ? current === false : current !== false;
    })
    .map((tool) => ({ kind: "tool_toggle" as const, target: toolTarget(tool.name), value }));
}

function ToolRow({
  tool,
  overrides,
  onOverride,
  allExpanded,
  readOnly,
  initialExpanded,
}: {
  tool: ToolDef;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  allExpanded: boolean;
  readOnly?: boolean;
  initialExpanded: boolean;
}) {
  const target = toolTarget(tool.name);
  const {
    checked,
    isModified,
    expanded,
    setExpanded,
    localText,
    setLocalText,
    textRef,
    handleToggle,
    commitText,
    handleReset,
  } = useEditableOverride({
    originalValue: tool.description,
    overrides,
    onOverride,
    toggleKind: "tool_toggle",
    textKind: "tool_description",
    target,
    initialExpanded,
  });

  // Section-level Expand/Collapse All drives per-row state. Individual
  // row clicks can still override this until the bulk button fires again.
  useEffect(() => {
    setExpanded(allExpanded);
  }, [allExpanded, setExpanded]);

  // ToolRow tracks modification via both toggle and description overrides
  const modified =
    hasOverride(overrides, "tool_toggle", target) ||
    hasOverride(overrides, "tool_description", target);

  // Mirror BlockRow: show an ``orig → current`` delta when the user has
  // edited the description. Rebuild the char count with the live text so
  // the number tracks the textarea instead of freezing at the pre-edit
  // value. SizeDelta collapses to the raw number when current === original.
  const baseToolChars = toolChars(tool);
  const currentToolChars = isModified ? toolChars(tool, localText) : baseToolChars;

  return (
    <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
      <div className="flex items-center gap-3 px-4 py-2">
        {/* Toggle is only meaningful when the consumer can flip it. In
            readOnly the opacity-40 wrapper already communicates the
            disabled state and the modified dot carries the edit signal. */}
        {!readOnly && (
          <Toggle
            checked={checked}
            onChange={handleToggle}
            label={`Toggle ${tool.name}`}
            size="sm"
          />
        )}
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-[13px] text-txt-2 flex-1 min-w-0 truncate text-left cursor-pointer hover:text-txt transition-colors"
        >
          {displayName(tool.name)}
        </button>
        <div className="ml-auto">
          <SizeDelta original={baseToolChars} current={currentToolChars} />
        </div>
        {modified && <span className="h-1 w-1 rounded-full bg-amber shrink-0" />}
      </div>
      {checked && expanded && (
        <div className="px-4 pb-3 space-y-2">
          <div className="space-y-1">
            <span className="label">Description</span>
            <TextOverrideEditor
              original={tool.description}
              value={localText}
              onChange={setLocalText}
              onBlur={commitText}
              textareaRef={textRef}
              isModified={isModified}
              onReset={handleReset}
              readOnly={readOnly}
            />
          </div>
          <details className="group">
            <summary className="label text-txt-3 cursor-pointer hover:text-txt-2 transition-colors">
              Schema
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto bg-canvas p-3 text-[12px] text-txt-3 whitespace-pre-wrap border border-edge-subtle">
              {JSON.stringify(tool.input_schema, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  );
}

function ToolGroupSection({
  group,
  overrides,
  onOverride,
  allExpanded,
  readOnly,
  startExpanded,
}: {
  group: EditorToolGroup;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  allExpanded: boolean;
  readOnly?: boolean;
  startExpanded: boolean;
}) {
  // Groups default collapsed so opening OVERLAY doesn't dump every
  // tool row in view — expand is opt-in (per-group `+` or the
  // section-wide Expand All toggle). Export serialization can opt into
  // a force-mounted first render.
  const [collapsed, setCollapsed] = useState(!startExpanded);
  const checkedCount = group.tools.filter(
    (t) => overrideValue<boolean>(overrides, "tool_toggle", toolTarget(t.name)) !== false,
  ).length;
  const overrideCount = group.tools.filter(
    (t) =>
      hasOverride(overrides, "tool_toggle", toolTarget(t.name)) ||
      hasOverride(overrides, "tool_description", toolTarget(t.name)),
  ).length;

  const groupAll = () => {
    const batch = bulkToggle(group.tools, overrides, null);
    if (batch.length) onOverride(batch);
  };

  const groupNone = () => {
    const batch = bulkToggle(group.tools, overrides, false);
    if (batch.length) onOverride(batch);
  };

  // Mirror the per-tool disabled treatment (opacity-40 on ToolRow) so a
  // fully-disabled group reads the same at the group level.
  const allDisabled = checkedCount === 0;
  const overrideLabel = overrideCountLabel(overrideCount, readOnly);

  return (
    <div
      data-testid={`tool-group-${group.prefix}`}
      className={`card-flush transition-opacity ${allDisabled ? "opacity-40" : ""}`}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          className="text-[13px] text-txt-3 cursor-pointer w-4 hover:text-txt-2"
          onClick={() => setCollapsed((v) => !v)}
        >
          {collapsed ? "+" : "\u2212"}
        </button>
        <span className="text-[13px] font-medium text-txt">{group.prefix}</span>
        <span className="label text-txt-3 metric-num">
          {checkedCount}/{group.tools.length}
        </span>
        <span className="label text-txt-3 metric-num">
          {group.totalChars.toLocaleString()} chars
        </span>
        {overrideCount > 0 && (
          <span className="chip text-amber">
            {overrideCount} {overrideLabel}
          </span>
        )}
        {/* Per-group all/none only make sense when the reader can drive
            them. In readOnly the group is purely informational. */}
        {!readOnly && (
          <div className="ml-auto flex gap-0">
            <button
              type="button"
              className="btn label text-txt-3 hover:text-txt cursor-pointer px-2 py-1 transition-colors"
              onClick={groupAll}
            >
              all
            </button>
            <button
              type="button"
              className="btn label text-txt-3 hover:text-txt cursor-pointer px-2 py-1 transition-colors"
              onClick={groupNone}
            >
              none
            </button>
          </div>
        )}
      </div>
      {!collapsed && (
        <>
          <div className="hairline-x" />
          <div>
            {group.tools.map((tool, i) => (
              <div key={tool.name}>
                <ToolRow
                  tool={tool}
                  overrides={overrides}
                  onOverride={onOverride}
                  allExpanded={allExpanded}
                  readOnly={readOnly}
                  initialExpanded={startExpanded}
                />
                {i < group.tools.length - 1 && <div className="hairline-x mx-4" />}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function ToolsSection({
  tools,
  overrides = [],
  onOverride = noopOverride,
  readOnly,
  expandAll = false,
}: ToolsSectionProps) {
  const groups = useMemo(() => buildEditorGroups(tools), [tools]);
  const [allExpanded, setAllExpanded] = useState(expandAll);

  if (tools.length === 0) return null;

  const totalOverrides = overrides.filter(
    (o) => o.kind === "tool_toggle" || o.kind === "tool_description",
  ).length;
  const overrideLabel = overrideCountLabel(totalOverrides, readOnly);

  const checkAll = () => {
    const batch = bulkToggle(tools, overrides, null);
    if (batch.length) onOverride(batch);
  };

  const uncheckAll = () => {
    const batch = bulkToggle(tools, overrides, false);
    if (batch.length) onOverride(batch);
  };

  const dropAllMcp = () => {
    const batch = bulkToggle(tools, overrides, false, (tool) => tool.name.includes("__"));
    if (batch.length) onOverride(batch);
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="section-rule flex-1">
          <span className="label">Tools &middot; {tools.length}</span>
          {totalOverrides > 0 && (
            <span className="chip text-amber ml-2">
              {totalOverrides} {overrideLabel}
            </span>
          )}
        </div>
        {/* Bulk controls drop out of the read-only view. View control —
            bulk expand/collapse all tool descriptions — is visually
            separated from the data-action cluster (All / None / Drop
            MCP) because it affects display, not tool enablement. */}
        {!readOnly && (
          <>
            <button
              type="button"
              className="btn label text-txt-3 hover:text-txt cursor-pointer border border-edge px-3 py-1.5 shrink-0 transition-colors"
              onClick={() => setAllExpanded((v) => !v)}
            >
              {allExpanded ? "Collapse All" : "Expand All"}
            </button>
            <div className="flex gap-0 shrink-0">
              <button
                type="button"
                className="btn label text-txt-3 hover:text-txt cursor-pointer px-3 py-1.5 border border-edge transition-colors"
                onClick={checkAll}
              >
                All
              </button>
              <button
                type="button"
                className="btn label text-txt-3 hover:text-txt cursor-pointer px-3 py-1.5 border border-edge border-l-0 transition-colors"
                onClick={uncheckAll}
              >
                None
              </button>
              <button
                type="button"
                className="btn label text-rose/80 hover:text-rose cursor-pointer px-3 py-1.5 border border-edge border-l-0 transition-colors"
                onClick={dropAllMcp}
              >
                Drop MCP
              </button>
            </div>
          </>
        )}
      </div>
      <div className="space-y-2">
        {groups.map((group) => (
          <ToolGroupSection
            key={group.prefix}
            group={group}
            overrides={overrides}
            onOverride={onOverride}
            allExpanded={allExpanded}
            readOnly={readOnly}
            startExpanded={expandAll}
          />
        ))}
      </div>
    </section>
  );
}
