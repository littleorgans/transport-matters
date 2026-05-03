import type { InternalRequest, OverrideAudit } from "../../types";
import { type CharBreakdown, CharsLedger, countCharsParts } from "./EditorLedger";

interface EditorActionsProps {
  originalIr: InternalRequest;
  audit: OverrideAudit | null;
  editedIr: InternalRequest;
  overridesCount: number;
  overridesEnabled: boolean;
  onToggleOverrides: () => void;
  onClearOverrides: () => void;
  onForward: () => void;
  onForwardUnmodified: () => void;
  onDrop: () => void;
  loading: boolean;
}

function Spinner() {
  return (
    <span className="inline-block h-3 w-3 rounded-full border-2 border-current/30 border-t-current spinner" />
  );
}

export function EditorActions({
  originalIr,
  audit,
  editedIr,
  overridesCount,
  overridesEnabled,
  onToggleOverrides,
  onClearOverrides,
  onForward,
  onForwardUnmodified,
  onDrop,
  loading,
}: EditorActionsProps) {
  const fallback = countCharsParts(originalIr);
  const fallbackAfter = countCharsParts(editedIr);

  const before: CharBreakdown = audit
    ? {
        system: audit.system_chars_before,
        tools: audit.tools_chars_before,
        messages: audit.messages_chars_before,
        total: audit.chars_before,
      }
    : fallback;

  const after: CharBreakdown = audit
    ? {
        system: audit.system_chars_after,
        tools: audit.tools_chars_after,
        messages: audit.messages_chars_after,
        total: audit.chars_after,
      }
    : fallbackAfter;

  const appliedCount = audit?.entries.filter((e) => e.applied).length ?? 0;
  const storedCount = overridesCount;

  const btnBase =
    "btn cursor-pointer border px-4 py-2 text-[12px] font-medium uppercase tracking-[0.14em] min-w-[110px] whitespace-nowrap transition-colors";

  return (
    <div className="top-highlight bg-surface">
      <div className="flex items-center justify-end gap-2 px-6 py-2">
        <button
          type="button"
          disabled={loading}
          onClick={onDrop}
          className={`${btnBase} border-rose/25 bg-rose/5 text-rose hover:bg-rose/10`}
        >
          {loading ? <Spinner /> : "Drop"}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForwardUnmodified}
          className={`${btnBase} border-edge bg-surface text-txt-2 hover:bg-raised hover:text-txt`}
        >
          {loading ? <Spinner /> : "Pass Through"}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForward}
          className={`${btnBase} border-accent/30 bg-accent/8 text-accent hover:bg-accent/15`}
        >
          {loading ? <Spinner /> : "Forward"}
        </button>
      </div>

      <div className="hairline-x" />

      <CharsLedger
        before={before}
        after={after}
        overridesFooter={{
          storedCount,
          appliedCount,
          enabled: overridesEnabled,
          onToggle: onToggleOverrides,
          onClear: onClearOverrides,
        }}
      />

      <div className="hairline-x" />
    </div>
  );
}
