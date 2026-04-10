import type { Rule } from "../types";
import { Toggle } from "./Toggle";

interface RulesListProps {
  rules: Rule[];
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

const ACTION_COLORS: Record<string, string> = {
  strip_tools: "text-rose",
  strip_thinking: "text-lavender",
  strip_system_part: "text-amber",
  truncate_system_part: "text-teal",
  truncate_tool_result: "text-sky",
  rewrite_tool_description: "text-sage",
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
        <span key={chip} className="border border-edge bg-canvas px-2 py-0.5 label">
          {chip}
        </span>
      ))}
    </div>
  );
}

export function RulesList({ rules, onToggle, onDelete }: RulesListProps) {
  if (rules.length === 0) {
    return (
      <div className="flex items-center justify-center p-10">
        <span className="label">No rules configured</span>
      </div>
    );
  }

  return (
    <div>
      {rules.map((rule) => {
        const tone = ACTION_COLORS[rule.action] ?? "text-txt-2";
        return (
          <div key={rule.id} className="relative px-5 py-4 space-y-2.5">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[12px] font-medium text-txt truncate">{rule.name}</span>
              <div className="flex items-center gap-3 shrink-0">
                <Toggle
                  checked={rule.enabled}
                  onChange={(next) => onToggle(rule.id, next)}
                  label={`Toggle ${rule.name}`}
                />
                <button
                  type="button"
                  onClick={() => onDelete(rule.id)}
                  className="btn text-txt-3 hover:text-rose text-[13px] cursor-pointer transition-colors"
                  aria-label={`Delete ${rule.name}`}
                >
                  &times;
                </button>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-2">
                <span className={`inline-block h-3 w-px ${tone.replace("text-", "bg-")}/60`} />
                <span className={`label ${tone}`}>{rule.action}</span>
              </span>
              <span className="label text-txt-3 metric-num">{rule.applied_count} applied</span>
            </div>
            <ScopeChips scope={rule.scope} />
            <span className="absolute bottom-0 left-5 right-5 h-px bg-edge-subtle" />
          </div>
        );
      })}
    </div>
  );
}
