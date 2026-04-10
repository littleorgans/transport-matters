import type { Rule } from "../types";

interface RulesListProps {
  rules: Rule[];
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

const ACTION_COLORS: Record<string, string> = {
  strip_tools: "bg-rose-900/40 text-rose-400",
  strip_thinking: "bg-violet-900/40 text-violet-400",
  strip_system_part: "bg-amber-900/40 text-amber-400",
  truncate_system_part: "bg-teal-900/40 text-teal-400",
  truncate_tool_result: "bg-sky-900/40 text-sky-400",
  rewrite_tool_description: "bg-lime-900/40 text-lime-400",
};

function ScopeChips({ scope }: { scope: Rule["scope"] }) {
  const chips: string[] = [];
  if (scope.global) chips.push("Global");
  if (scope.session_id) chips.push(`session: ${scope.session_id}`);
  if (scope.device_id) chips.push(`device: ${scope.device_id}`);
  if (scope.account_id) chips.push(`account: ${scope.account_id}`);
  if (scope.model) chips.push(`model: ${scope.model}`);

  return (
    <div className="flex flex-wrap gap-1">
      {chips.map((chip) => (
        <span key={chip} className="rounded bg-zinc-700/50 px-1.5 py-0.5 text-xs text-zinc-400">
          {chip}
        </span>
      ))}
    </div>
  );
}

export function RulesList({ rules, onToggle, onDelete }: RulesListProps) {
  if (rules.length === 0) {
    return (
      <div className="flex items-center justify-center p-6 text-zinc-500 text-sm">
        No rules configured
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-800">
      {rules.map((rule) => {
        const colorClass = ACTION_COLORS[rule.action] ?? "bg-zinc-700 text-zinc-300";
        return (
          <div key={rule.id} className="px-3 py-2.5 space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-zinc-200 truncate">{rule.name}</span>
              <div className="flex items-center gap-2 shrink-0">
                <label className="flex items-center gap-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rule.enabled}
                    onChange={() => onToggle(rule.id, !rule.enabled)}
                    className="accent-emerald-500"
                    aria-label={`Toggle ${rule.name}`}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => onDelete(rule.id)}
                  className="text-zinc-500 hover:text-red-400 text-sm cursor-pointer"
                  aria-label={`Delete ${rule.name}`}
                >
                  &times;
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-xs ${colorClass}`}>{rule.action}</span>
              <span className="text-xs text-zinc-500">{rule.applied_count} applied</span>
            </div>
            <ScopeChips scope={rule.scope} />
          </div>
        );
      })}
    </div>
  );
}
