import { useMemo, useState } from "react";
import type { ToolDef } from "../../types";

interface ToolsSectionProps {
  tools: ToolDef[];
  onChange: (tools: ToolDef[]) => void;
}

interface ToolGroup {
  prefix: string;
  tools: ToolDef[];
  totalChars: number;
}

function toolCharCount(t: ToolDef): number {
  return t.name.length + t.description.length + JSON.stringify(t.input_schema).length;
}

function getPrefix(name: string): string {
  const idx = name.indexOf("__");
  return idx >= 0 ? name.slice(0, idx) : "Built-in";
}

function displayName(name: string): string {
  const idx = name.indexOf("__");
  return idx >= 0 ? name.slice(idx + 2) : name;
}

function groupTools(tools: ToolDef[]): ToolGroup[] {
  const map = new Map<string, ToolDef[]>();
  for (const tool of tools) {
    const prefix = getPrefix(tool.name);
    const group = map.get(prefix);
    if (group) {
      group.push(tool);
    } else {
      map.set(prefix, [tool]);
    }
  }

  const groups: ToolGroup[] = [];
  for (const [prefix, groupTools] of map.entries()) {
    const sorted = [...groupTools].sort((a, b) => b.description.length - a.description.length);
    groups.push({
      prefix,
      tools: sorted,
      totalChars: sorted.reduce((sum, t) => sum + toolCharCount(t), 0),
    });
  }

  return groups.sort((a, b) => {
    if (a.prefix === "Built-in") return -1;
    if (b.prefix === "Built-in") return 1;
    return a.prefix.localeCompare(b.prefix);
  });
}

function ToolGroupSection({
  group,
  checkedNames,
  onToggle,
  onGroupAll,
  onGroupNone,
}: {
  group: ToolGroup;
  checkedNames: Set<string>;
  onToggle: (name: string) => void;
  onGroupAll: () => void;
  onGroupNone: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const checkedCount = group.tools.filter((t) => checkedNames.has(t.name)).length;

  return (
    <div className="border border-edge rounded-md overflow-hidden">
      <div className="flex items-center gap-2.5 px-4 py-2.5 bg-surface">
        <button
          type="button"
          className="text-[11px] text-txt-3 cursor-pointer w-4"
          onClick={() => setCollapsed((v) => !v)}
        >
          {collapsed ? "+" : "\u2212"}
        </button>
        <span className="text-[11px] font-medium text-txt-2">{group.prefix}</span>
        <span className="text-[10px] text-txt-3 tabular-nums">
          {checkedCount}/{group.tools.length}
        </span>
        <span className="text-[10px] text-txt-3 tabular-nums">
          {group.totalChars.toLocaleString()} chars
        </span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            className="btn text-[10px] text-txt-3 hover:text-txt-2 cursor-pointer px-1.5 py-0.5 rounded bg-raised transition-colors"
            onClick={onGroupAll}
          >
            all
          </button>
          <button
            type="button"
            className="btn text-[10px] text-txt-3 hover:text-txt-2 cursor-pointer px-1.5 py-0.5 rounded bg-raised transition-colors"
            onClick={onGroupNone}
          >
            none
          </button>
        </div>
      </div>
      {!collapsed && (
        <div className="divide-y divide-edge-subtle">
          {group.tools.map((tool) => (
            <div key={tool.name} className="flex items-center gap-2.5 px-4 py-2">
              <input
                type="checkbox"
                checked={checkedNames.has(tool.name)}
                onChange={() => onToggle(tool.name)}
              />
              <span className="text-[11px] text-txt-2">{displayName(tool.name)}</span>
              <span className="text-[10px] text-txt-3 ml-auto tabular-nums">
                {toolCharCount(tool).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function ToolsSection({ tools, onChange }: ToolsSectionProps) {
  const [checkedNames, setCheckedNames] = useState<Set<string>>(
    () => new Set(tools.map((t) => t.name)),
  );

  const groups = useMemo(() => groupTools(tools), [tools]);

  const emitChange = (nextChecked: Set<string>) => {
    onChange(tools.filter((t) => nextChecked.has(t.name)));
  };

  const toggleTool = (name: string) => {
    setCheckedNames((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      emitChange(next);
      return next;
    });
  };

  const checkAll = () => {
    const all = new Set(tools.map((t) => t.name));
    setCheckedNames(all);
    emitChange(all);
  };

  const uncheckAll = () => {
    const none = new Set<string>();
    setCheckedNames(none);
    emitChange(none);
  };

  const dropAllMcp = () => {
    const next = new Set(checkedNames);
    for (const t of tools) {
      if (t.name.includes("__")) {
        next.delete(t.name);
      }
    }
    setCheckedNames(next);
    emitChange(next);
  };

  const groupAll = (prefix: string) => {
    const group = groups.find((g) => g.prefix === prefix);
    if (!group) return;
    const next = new Set(checkedNames);
    for (const t of group.tools) {
      next.add(t.name);
    }
    setCheckedNames(next);
    emitChange(next);
  };

  const groupNone = (prefix: string) => {
    const group = groups.find((g) => g.prefix === prefix);
    if (!group) return;
    const next = new Set(checkedNames);
    for (const t of group.tools) {
      next.delete(t.name);
    }
    setCheckedNames(next);
    emitChange(next);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <h3 className="text-[10px] font-medium text-txt-3 uppercase tracking-[0.12em]">
          Tools ({tools.length})
        </h3>
        <div className="ml-auto flex gap-1.5">
          <button
            type="button"
            className="btn text-[10px] text-txt-3 hover:text-txt-2 cursor-pointer px-2 py-1 rounded-md bg-raised transition-colors"
            onClick={checkAll}
          >
            Check all
          </button>
          <button
            type="button"
            className="btn text-[10px] text-txt-3 hover:text-txt-2 cursor-pointer px-2 py-1 rounded-md bg-raised transition-colors"
            onClick={uncheckAll}
          >
            Uncheck all
          </button>
          <button
            type="button"
            className="btn text-[10px] text-txt-3 hover:text-txt-2 cursor-pointer px-2 py-1 rounded-md bg-raised transition-colors"
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
            checkedNames={checkedNames}
            onToggle={toggleTool}
            onGroupAll={() => groupAll(group.prefix)}
            onGroupNone={() => groupNone(group.prefix)}
          />
        ))}
      </div>
    </div>
  );
}
