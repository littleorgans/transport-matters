import type { Rule } from "../types";

interface RulesListProps {
  rules: Rule[];
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

const ACTION_COLORS: Record<string, string> = {
  strip_tools: "text-rose bg-rose/8",
  strip_thinking: "text-lavender bg-lavender/8",
  strip_system_part: "text-amber bg-amber/8",
  truncate_system_part: "text-teal bg-teal/8",
  truncate_tool_result: "text-sky bg-sky/8",
  rewrite_tool_description: "text-sage bg-sage/8",
};

function ScopeChips({ scope }: { scope: Rule["scope"] }) {
  const chips: string[] = [];
  if (scope.global) chips.push("Global");
  if (scope.session_id) chips.push(`session: ${scope.session_id}`);
  if (scope.device_id) chips.push(`device: ${scope.device_id}`);
  if (scope.account_id) chips.push(`account: ${scope.account_id}`);
  if (scope.model) chips.push(`model: ${scope.model}`);

  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <span key={chip} className="rounded bg-raised px-2 py-0.5 text-[10px] text-txt-3">
          {chip}
        </span>
      ))}
    </div>
  );
}

export function RulesList({ rules, onToggle, onDelete }: RulesListProps) {
  if (rules.length === 0) {
    return (
      <div className="flex items-center justify-center p-10 text-txt-3 text-[11px]">
        No rules configured
      </div>
    );
  }

  return (
    <div className="divide-y divide-edge-subtle">
      {rules.map((rule) => {
        const colorClass = ACTION_COLORS[rule.action] ?? "text-txt-2 bg-raised";
        return (
          <div key={rule.id} className="px-5 py-3.5 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[12px] font-medium text-txt truncate">{rule.name}</span>
              <div className="flex items-center gap-2.5 shrink-0">
                <label className="flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={rule.enabled}
                    onChange={() => onToggle(rule.id, !rule.enabled)}
                    aria-label={`Toggle ${rule.name}`}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => onDelete(rule.id)}
                  className="btn text-txt-3 hover:text-rose text-[12px] cursor-pointer transition-colors"
                  aria-label={`Delete ${rule.name}`}
                >
                  &times;
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2.5">
              <span className={`rounded px-2 py-0.5 text-[10px] ${colorClass}`}>{rule.action}</span>
              <span className="text-[10px] text-txt-3 tabular-nums">
                {rule.applied_count} applied
              </span>
            </div>
            <ScopeChips scope={rule.scope} />
          </div>
        );
      })}
    </div>
  );
}
