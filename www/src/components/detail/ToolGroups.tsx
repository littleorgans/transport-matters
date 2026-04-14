/**
 * Tool grouping + display for the detail view.
 *
 * Tools can number in the dozens once multiple MCP plugins are
 * attached. We group them by plugin and render each group as a
 * collapsible panel so the inspect view stays scannable.
 */

import { useState } from "react";

function pluginLabel(name: string): string {
  if (!name.startsWith("mcp__")) return "built-in";
  const parts = name.split("__");
  return (parts[1] ?? "").replace(/^plugin_/, "");
}

function shortName(name: string): string {
  if (!name.startsWith("mcp__")) return name;
  const parts = name.split("__");
  return parts[parts.length - 1] ?? name;
}

export function groupTools<T extends { name: string }>(tools: T[]): [string, T[]][] {
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

// Stable colour assignment per plugin label. The first call for
// any label picks the next palette slot and caches it so the same
// plugin keeps the same hue across renders.
const GROUP_HUES: Record<string, string> = {};
const PALETTE = ["text-sky", "text-lavender", "text-sage", "text-amber", "text-rose", "text-teal"];
let _paletteIdx = 0;

function groupColour(label: string): string {
  if (label === "built-in") return "text-txt-2";
  const existing = GROUP_HUES[label];
  if (existing) return existing;
  const colour = PALETTE[_paletteIdx % PALETTE.length] as string;
  GROUP_HUES[label] = colour;
  _paletteIdx++;
  return colour;
}

export function ToolGroup({ label, tools }: { label: string; tools: Array<{ name: string }> }) {
  const [open, setOpen] = useState(true);
  const colour = groupColour(label);
  const isBuiltIn = label === "built-in";

  return (
    <div
      className={`card-flush transition-colors ${
        open ? "top-highlight bg-raised/30" : "hover:bg-raised/15"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="group flex w-full cursor-pointer items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-3">
          {isBuiltIn ? (
            <span className="label text-txt-2">{label}</span>
          ) : (
            <span className={`chip ${colour}`}>{label}</span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <span className="flex items-baseline gap-1.5">
            <span className={`metric-num text-[15px] font-medium ${colour}`}>{tools.length}</span>
            <span className="label">tools</span>
          </span>
          <span className="relative inline-block h-3 w-3">
            <span
              className={`absolute inset-0 flex items-center justify-center text-[15px] leading-none text-txt-3 transition-opacity duration-150 group-hover:text-txt-2 ${
                open ? "opacity-0" : "opacity-100"
              }`}
            >
              {"+"}
            </span>
            <span
              className={`absolute inset-0 flex items-center justify-center text-[15px] leading-none text-txt-3 transition-opacity duration-150 group-hover:text-txt-2 ${
                open ? "opacity-100" : "opacity-0"
              }`}
            >
              {"\u2212"}
            </span>
          </span>
        </div>
      </button>

      {open && (
        <>
          <div className="hairline-x" />
          <div className="px-4 py-3">
            <div className="flex flex-wrap gap-1.5">
              {tools.map((t) => (
                <span
                  key={t.name}
                  title={t.name}
                  className={`border border-edge bg-canvas px-2 py-1 font-mono text-[12px] ${colour}`}
                >
                  {shortName(t.name)}
                </span>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
