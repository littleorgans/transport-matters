import type { PipelineAudit } from "../../types";

interface AuditPanelProps {
  audit: PipelineAudit | null;
}

export function AuditPanel({ audit }: AuditPanelProps) {
  if (!audit || audit.rules_applied.length === 0) {
    return <div className="text-[11px] text-txt-3 p-5">No pipeline rules applied.</div>;
  }

  const delta = audit.chars_after - audit.chars_before;
  const pct = audit.chars_before > 0 ? Math.round((Math.abs(delta) / audit.chars_before) * 100) : 0;
  const tokensSaved = Math.round(Math.abs(delta) / 4);

  return (
    <div className="space-y-5 p-5">
      <h3 className="text-[10px] font-medium text-txt-3 uppercase tracking-[0.12em]">
        Pipeline Audit
      </h3>

      <div className="text-[11px] text-txt-2 space-y-1">
        <div className="tabular-nums">
          {audit.chars_before.toLocaleString()} chars &rarr; {audit.chars_after.toLocaleString()}{" "}
          chars
        </div>
        {delta !== 0 && (
          <div className={delta < 0 ? "text-sage" : "text-amber"}>
            {delta < 0 ? "\u2212" : "+"}
            {pct}% (~{tokensSaved.toLocaleString()} tokens)
          </div>
        )}
      </div>

      <div className="space-y-2">
        {audit.rules_applied.map((rule) => (
          <div key={rule.id} className="rounded-md bg-raised/50 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-txt-2">{rule.name}</span>
              <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] text-txt-3">
                {rule.action}
              </span>
            </div>
            <div className="text-[10px] text-txt-3 mt-1">
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
