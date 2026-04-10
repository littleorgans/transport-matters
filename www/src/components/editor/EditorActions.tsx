import type { InternalRequest, PipelineAudit } from "../../types";

interface EditorActionsProps {
  originalIr: InternalRequest;
  pipelineAudit: PipelineAudit | null;
  editedIr: InternalRequest;
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

function Spinner() {
  return (
    <span className="inline-block h-3 w-3 rounded-full border-2 border-current/30 border-t-current spinner" />
  );
}

export function EditorActions({
  originalIr,
  pipelineAudit,
  editedIr,
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
    <div className="flex items-center gap-3">
      {/* Compact stats */}
      <div className="flex items-center gap-3 text-[10px] text-txt-3 tabular-nums mr-2">
        <span>{editedChars.toLocaleString()} chars</span>
        {delta !== 0 && (
          <span className={delta < 0 ? "text-sage" : "text-amber"}>
            {delta < 0 ? "\u2212" : "+"}
            {deltaPct}%
          </span>
        )}
      </div>

      {/* Action buttons */}
      <button
        type="button"
        disabled={loading}
        onClick={onDrop}
        className="btn cursor-pointer rounded-md border border-rose/20 bg-rose/8 px-3 py-1.5 text-[11px] font-medium text-rose hover:bg-rose/15 transition-colors"
      >
        {loading ? <Spinner /> : "Drop"}
      </button>
      <button
        type="button"
        disabled={loading}
        onClick={onForwardUnmodified}
        className="btn cursor-pointer rounded-md border border-edge bg-raised px-3 py-1.5 text-[11px] font-medium text-txt-2 hover:text-txt hover:bg-hover transition-colors"
      >
        {loading ? <Spinner /> : "Pass Through"}
      </button>
      <button
        type="button"
        disabled={loading}
        onClick={onForward}
        className="btn cursor-pointer rounded-md border border-sky/20 bg-sky/10 px-3 py-1.5 text-[11px] font-medium text-sky hover:bg-sky/15 transition-colors"
      >
        {loading ? <Spinner /> : "Forward"}
      </button>
    </div>
  );
}
