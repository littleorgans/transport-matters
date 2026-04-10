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

  // Put "Built-in" first, then alphabetical
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
    <div className="border border-zinc-800 rounded">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900">
        <button
          type="button"
          className="text-xs text-zinc-500 cursor-pointer"
          onClick={() => setCollapsed((v) => !v)}
        >
          {collapsed ? "+" : "-"}
        </button>
        <span className="text-xs font-medium text-zinc-300">{group.prefix}</span>
        <span className="text-xs text-zinc-500">
          {checkedCount}/{group.tools.length}
        </span>
        <span className="text-xs text-zinc-600">{group.totalChars.toLocaleString()} chars</span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            className="text-xs text-zinc-500 hover:text-zinc-300 cursor-pointer px-1"
            onClick={onGroupAll}
          >
            all
          </button>
          <button
            type="button"
            className="text-xs text-zinc-500 hover:text-zinc-300 cursor-pointer px-1"
            onClick={onGroupNone}
          >
            none
          </button>
        </div>
      </div>
      {!collapsed && (
        <div className="divide-y divide-zinc-800/50">
          {group.tools.map((tool) => (
            <div key={tool.name} className="flex items-center gap-2 px-3 py-1">
              <input
                type="checkbox"
                checked={checkedNames.has(tool.name)}
                onChange={() => onToggle(tool.name)}
                className="accent-emerald-500"
              />
              <span className="font-mono text-xs text-zinc-300">{displayName(tool.name)}</span>
              <span className="text-xs text-zinc-600 ml-auto">
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
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
          Tools ({tools.length})
        </h3>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            className="text-xs text-zinc-500 hover:text-zinc-300 cursor-pointer px-1.5 py-0.5 rounded bg-zinc-800"
            onClick={checkAll}
          >
            Check all
          </button>
          <button
            type="button"
            className="text-xs text-zinc-500 hover:text-zinc-300 cursor-pointer px-1.5 py-0.5 rounded bg-zinc-800"
            onClick={uncheckAll}
          >
            Uncheck all
          </button>
          <button
            type="button"
            className="text-xs text-zinc-500 hover:text-zinc-300 cursor-pointer px-1.5 py-0.5 rounded bg-zinc-800"
            onClick={dropAllMcp}
          >
            Drop all MCP
          </button>
        </div>
      </div>
      <div className="space-y-1">
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
