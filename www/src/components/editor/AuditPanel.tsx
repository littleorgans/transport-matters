import type { PipelineAudit } from "../../types";

interface AuditPanelProps {
  audit: PipelineAudit | null;
}

export function AuditPanel({ audit }: AuditPanelProps) {
  if (!audit || audit.rules_applied.length === 0) {
    return (
      <div className="p-6">
        <span className="label">No pipeline rules applied</span>
      </div>
    );
  }

  const delta = audit.chars_after - audit.chars_before;
  const pct = audit.chars_before > 0 ? Math.round((Math.abs(delta) / audit.chars_before) * 100) : 0;
  const tokensSaved = Math.round(Math.abs(delta) / 4);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-2.5">
        <span className="inline-block h-3 w-px bg-lavender/50" />
        <span className="label">Pipeline Audit</span>
      </div>

      <div className="space-y-2">
        <div className="flex items-baseline gap-2 text-[11px]">
          <span className="text-txt metric-num">{audit.chars_before.toLocaleString()}</span>
          <span className="text-txt-3">&rarr;</span>
          <span className="text-txt metric-num">{audit.chars_after.toLocaleString()}</span>
          <span className="label">chars</span>
        </div>
        {delta !== 0 && (
          <div className={`text-[11px] metric-num ${delta < 0 ? "text-sage" : "text-amber"}`}>
            {delta < 0 ? "\u2212" : "+"}
            {pct}% &middot; ~{tokensSaved.toLocaleString()} tokens
          </div>
        )}
      </div>

      <div className="space-y-2">
        {audit.rules_applied.map((rule) => (
          <div key={rule.id} className="card-flush px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-txt-2 truncate">{rule.name}</span>
              <span className="border border-edge bg-canvas px-1.5 py-0.5 label">
                {rule.action}
              </span>
            </div>
            <div className="mt-1.5 label">
              {Object.entries(rule.removed)
                .filter(([, v]) => v !== 0)
                .map(([k, v]) => `${v} ${k}`)
                .join("  \u00b7  ") || "no removals"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
