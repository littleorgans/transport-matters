import type { PipelineAudit } from "../../types";

interface AuditPanelProps {
  audit: PipelineAudit | null;
}

export function AuditPanel({ audit }: AuditPanelProps) {
  if (!audit || audit.rules_applied.length === 0) {
    return <div className="text-xs text-zinc-600 p-3">No pipeline rules applied.</div>;
  }

  const delta = audit.chars_after - audit.chars_before;
  const pct = audit.chars_before > 0 ? Math.round((Math.abs(delta) / audit.chars_before) * 100) : 0;
  const tokensSaved = Math.round(Math.abs(delta) / 4);

  return (
    <div className="space-y-3 p-3">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
        Pipeline Audit
      </h3>

      <div className="text-xs text-zinc-400 space-y-0.5">
        <div>
          {audit.chars_before.toLocaleString()} chars <span className="text-zinc-600">{">"}</span>{" "}
          {audit.chars_after.toLocaleString()} chars
        </div>
        {delta !== 0 && (
          <div className={delta < 0 ? "text-emerald-500" : "text-amber-500"}>
            {delta < 0 ? "-" : "+"}
            {pct}% (~{tokensSaved.toLocaleString()} tokens)
          </div>
        )}
      </div>

      <div className="space-y-1">
        {audit.rules_applied.map((rule) => (
          <div key={rule.id} className="rounded bg-zinc-800/50 px-2 py-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-zinc-300">{rule.name}</span>
              <span className="rounded bg-zinc-700 px-1 py-0.5 text-xs text-zinc-400 font-mono">
                {rule.action}
              </span>
            </div>
            <div className="text-xs text-zinc-600 mt-0.5">
              {Object.entries(rule.removed)
                .filter(([, v]) => v !== 0)
                .map(([k, v]) => `${v} ${k}`)
                .join(", ") || "no removals"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
