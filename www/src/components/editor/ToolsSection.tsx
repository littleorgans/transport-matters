import { useEffect, useMemo, useState } from "react";
import { useEditableOverride } from "../../hooks/useEditableOverride";
import { hasOverride, overrideValue } from "../../lib/overrides";
import type { Override, ToolDef } from "../../types";
import { inputClass, OriginalPreview } from "../detail/atoms";
import { groupTools } from "../detail/ToolGroups";
import { Toggle } from "../Toggle";

interface ToolsSectionProps {
  tools: ToolDef[];
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

interface EditorToolGroup {
  prefix: string;
  tools: ToolDef[];
  totalChars: number;
}

function toolCharCount(t: ToolDef): number {
  return t.name.length + t.description.length + JSON.stringify(t.input_schema).length;
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
      totalChars: sorted.reduce((sum, t) => sum + toolCharCount(t), 0),
    };
  });
}

function ToolRow({
  tool,
  overrides,
  onOverride,
  allExpanded,
}: {
  tool: ToolDef;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  allExpanded: boolean;
}) {
  const target = `tool:${tool.name}`;
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
    initialExpanded: false,
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

  return (
    <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
      <div className="flex items-center gap-3 px-4 py-2">
        <Toggle checked={checked} onChange={handleToggle} label={`Toggle ${tool.name}`} size="sm" />
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-[13px] text-txt-2 flex-1 min-w-0 truncate text-left cursor-pointer hover:text-txt transition-colors"
        >
          {displayName(tool.name)}
        </button>
        <span className="label text-txt-3 ml-auto metric-num shrink-0">
          {toolCharCount(tool).toLocaleString()}
        </span>
        {modified && <span className="h-1 w-1 rounded-full bg-amber shrink-0" />}
      </div>
      {checked && expanded && (
        <div className="px-4 pb-3 space-y-2">
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="label">Description</span>
              {isModified && (
                <button
                  type="button"
                  className="label text-txt-3 hover:text-amber cursor-pointer transition-colors"
                  onClick={handleReset}
                >
                  reset
                </button>
              )}
            </div>
            <textarea
              ref={textRef}
              className={inputClass}
              value={localText}
              onChange={(e) => setLocalText(e.target.value)}
              onBlur={commitText}
            />
          </div>
          {isModified && <OriginalPreview text={tool.description} />}
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
}: {
  group: EditorToolGroup;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  allExpanded: boolean;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const checkedCount = group.tools.filter(
    (t) => overrideValue<boolean>(overrides, "tool_toggle", `tool:${t.name}`) !== false,
  ).length;
  const overrideCount = group.tools.filter(
    (t) =>
      hasOverride(overrides, "tool_toggle", `tool:${t.name}`) ||
      hasOverride(overrides, "tool_description", `tool:${t.name}`),
  ).length;

  const groupAll = () => {
    const batch: Override[] = group.tools
      .filter((t) => overrideValue<boolean>(overrides, "tool_toggle", `tool:${t.name}`) === false)
      .map((t) => ({ kind: "tool_toggle" as const, target: `tool:${t.name}`, value: null }));
    if (batch.length) onOverride(batch);
  };

  const groupNone = () => {
    const batch: Override[] = group.tools
      .filter((t) => overrideValue<boolean>(overrides, "tool_toggle", `tool:${t.name}`) !== false)
      .map((t) => ({ kind: "tool_toggle" as const, target: `tool:${t.name}`, value: false }));
    if (batch.length) onOverride(batch);
  };

  return (
    <div className="card-flush">
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
            {overrideCount} override{overrideCount !== 1 ? "s" : ""}
          </span>
        )}
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

export function ToolsSection({ tools, overrides, onOverride }: ToolsSectionProps) {
  const groups = useMemo(() => buildEditorGroups(tools), [tools]);
  const [allExpanded, setAllExpanded] = useState(false);

  if (tools.length === 0) return null;

  const totalOverrides = overrides.filter(
    (o) => o.kind === "tool_toggle" || o.kind === "tool_description",
  ).length;

  const checkAll = () => {
    const batch: Override[] = tools
      .filter((t) => overrideValue<boolean>(overrides, "tool_toggle", `tool:${t.name}`) === false)
      .map((t) => ({ kind: "tool_toggle" as const, target: `tool:${t.name}`, value: null }));
    if (batch.length) onOverride(batch);
  };

  const uncheckAll = () => {
    const batch: Override[] = tools
      .filter((t) => overrideValue<boolean>(overrides, "tool_toggle", `tool:${t.name}`) !== false)
      .map((t) => ({ kind: "tool_toggle" as const, target: `tool:${t.name}`, value: false }));
    if (batch.length) onOverride(batch);
  };

  const dropAllMcp = () => {
    const batch: Override[] = tools
      .filter(
        (t) =>
          t.name.includes("__") &&
          overrideValue<boolean>(overrides, "tool_toggle", `tool:${t.name}`) !== false,
      )
      .map((t) => ({ kind: "tool_toggle" as const, target: `tool:${t.name}`, value: false }));
    if (batch.length) onOverride(batch);
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="section-rule flex-1">
          <span className="label">Tools &middot; {tools.length}</span>
          {totalOverrides > 0 && (
            <span className="chip text-amber ml-2">
              {totalOverrides} override{totalOverrides !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        {/* View control — bulk expand/collapse all tool descriptions.
            Visually separated from the data-action cluster (All / None /
            Drop MCP) because it affects display, not tool enablement. */}
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
      </div>
      <div className="space-y-2">
        {groups.map((group) => (
          <ToolGroupSection
            key={group.prefix}
            group={group}
            overrides={overrides}
            onOverride={onOverride}
            allExpanded={allExpanded}
          />
        ))}
      </div>
    </section>
  );
}
