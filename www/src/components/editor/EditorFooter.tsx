import type { InternalRequest, PipelineAudit } from "../../types";

interface EditorFooterProps {
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

export function EditorFooter({
  originalIr,
  pipelineAudit,
  editedIr,
  onForward,
  onForwardUnmodified,
  onDrop,
  loading,
}: EditorFooterProps) {
  const originalChars = pipelineAudit?.chars_before ?? countChars(originalIr);
  const pipelineChars = pipelineAudit?.chars_after ?? null;
  const editedChars = countChars(editedIr);

  const originalTokens = Math.round(originalChars / 4);
  const pipelinePct =
    pipelineChars !== null && originalChars > 0
      ? Math.round(((originalChars - pipelineChars) / originalChars) * 100)
      : null;

  return (
    <div className="flex items-center gap-4 border-t border-zinc-800 bg-zinc-900 px-4 py-2">
      <div className="flex gap-4 text-xs text-zinc-500">
        <span>
          Original: {originalChars.toLocaleString()} chars (~
          {originalTokens.toLocaleString()} tokens)
        </span>
        {pipelineChars !== null && (
          <span>
            Pipeline: {pipelineChars.toLocaleString()} chars
            {pipelinePct !== null && pipelinePct > 0 && (
              <span className="text-emerald-500"> (-{pipelinePct}%)</span>
            )}
          </span>
        )}
        <span>Edited: {editedChars.toLocaleString()} chars</span>
      </div>

      <div className="ml-auto flex gap-2">
        <button
          type="button"
          disabled={loading}
          onClick={onDrop}
          className="rounded px-3 py-1.5 text-xs font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 cursor-pointer"
        >
          Drop
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForwardUnmodified}
          className="rounded px-3 py-1.5 text-xs font-medium text-white bg-zinc-700 hover:bg-zinc-600 disabled:opacity-50 cursor-pointer"
        >
          Forward Unmodified
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForward}
          className="rounded px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 cursor-pointer"
        >
          Forward
        </button>
      </div>
    </div>
  );
}
