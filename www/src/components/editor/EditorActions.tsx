import type { InternalRequest, PipelineAudit } from "../../types";

interface EditorActionsProps {
  originalIr: InternalRequest;
  pipelineAudit: PipelineAudit | null;
  editedIr: InternalRequest;
  provider: string;
  model: string;
  onForward: () => void;
  onForwardUnmodified: () => void;
  onDrop: () => void;
  loading: boolean;
}

function countChars(ir: InternalRequest): number {
  const systemChars = ir.system.reduce((sum, p) => sum + p.text.length, 0);
  const toolsChars = ir.tools.reduce(
    (sum, t) => sum + t.name.length + t.description.length + JSON.stringify(t.input_schema).length,
    0,
  );
  let messagesChars = 0;
  for (const msg of ir.messages) {
    for (const block of msg.content) {
      messagesChars += JSON.stringify(block).length;
    }
  }
  return systemChars + toolsChars + messagesChars;
}

function displayModel(provider: string, model: string): string {
  const prefix = `${provider}/`;
  return model.startsWith(prefix) ? model.slice(prefix.length) : model;
}

function Spinner() {
  return (
    <span className="inline-block h-3 w-3 rounded-full border-2 border-current/30 border-t-current spinner" />
  );
}

export function EditorActions({
  originalIr,
  pipelineAudit,
  editedIr,
  provider,
  model,
  onForward,
  onForwardUnmodified,
  onDrop,
  loading,
}: EditorActionsProps) {
  const originalChars = pipelineAudit?.chars_before ?? countChars(originalIr);
  const editedChars = countChars(editedIr);
  const delta = editedChars - originalChars;
  const deltaPct = originalChars > 0 ? Math.round((Math.abs(delta) / originalChars) * 100) : 0;

  return (
    <div className="top-highlight bg-surface">
      {/* Row 1: action buttons */}
      <div className="flex items-center justify-end gap-3 px-8 py-4">
        <button
          type="button"
          disabled={loading}
          onClick={onDrop}
          className="btn cursor-pointer border border-rose/25 bg-rose/5 px-4 py-2 text-[10px] font-medium uppercase tracking-[0.14em] text-rose hover:bg-rose/10 transition-colors"
        >
          {loading ? <Spinner /> : "Drop"}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForwardUnmodified}
          className="btn cursor-pointer border border-edge bg-surface px-4 py-2 text-[10px] font-medium uppercase tracking-[0.14em] text-txt-2 hover:text-txt hover:bg-raised transition-colors"
        >
          {loading ? <Spinner /> : "Pass Through"}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForward}
          className="btn cursor-pointer border border-sky/30 bg-sky/8 px-4 py-2 text-[10px] font-medium uppercase tracking-[0.14em] text-sky hover:bg-sky/15 transition-colors"
        >
          {loading ? <Spinner /> : "Forward"}
        </button>
      </div>

      <div className="hairline-x" />

      {/* Row 2: model name + chars/delta */}
      <div className="flex items-baseline justify-between gap-4 px-8 py-3 bg-surface/60">
        <div className="flex items-baseline gap-3 min-w-0">
          <span className="label text-txt-3">{provider}</span>
          <span className="text-edge-strong">/</span>
          <span className="text-[13px] text-txt truncate">{displayModel(provider, model)}</span>
        </div>
        <div className="flex items-baseline gap-6 shrink-0">
          <div className="flex items-baseline gap-2">
            <span className="label">chars</span>
            <span className="text-[11px] text-txt metric-num">{editedChars.toLocaleString()}</span>
          </div>
          {delta !== 0 && (
            <div className="flex items-baseline gap-2">
              <span className="label">delta</span>
              <span className={`text-[11px] metric-num ${delta < 0 ? "text-sage" : "text-amber"}`}>
                {delta < 0 ? "\u2212" : "+"}
                {deltaPct}%
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="hairline-x" />
    </div>
  );
}
