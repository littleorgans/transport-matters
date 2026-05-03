export type EditorViewMode = "messages" | "overlay" | "raw";

const TAB_ORDER: EditorViewMode[] = ["messages", "overlay", "raw"];

interface BreakpointEditorTabsProps {
  viewMode: EditorViewMode;
  overridesCount: number;
  loading: boolean;
  onViewModeChange: (mode: EditorViewMode) => void;
  onSaveAsOverlay: () => void;
}

export function BreakpointEditorTabs({
  viewMode,
  overridesCount,
  loading,
  onViewModeChange,
  onSaveAsOverlay,
}: BreakpointEditorTabsProps) {
  return (
    <div className="flex items-stretch border-y border-edge">
      {TAB_ORDER.map((mode) => (
        <button
          key={mode}
          type="button"
          onClick={() => onViewModeChange(mode)}
          className={`relative cursor-pointer px-8 py-3 text-[12px] font-medium uppercase tracking-[0.14em] transition-all duration-150 ${
            viewMode === mode ? "tab-pressed text-txt" : "tab-rest text-txt-3 hover:text-txt-2"
          }`}
        >
          {mode}
        </button>
      ))}
      <div className="flex flex-1 tab-rest items-center justify-end gap-3 pr-3">
        {viewMode === "overlay" && (
          <>
            <span className="label text-txt-3">
              {overridesCount === 0
                ? "Make an override to save as an overlay"
                : `${overridesCount} override${overridesCount !== 1 ? "s" : ""} ready to lift`}
            </span>
            <button
              type="button"
              disabled={loading || overridesCount === 0}
              onClick={onSaveAsOverlay}
              className="btn cursor-pointer border border-amber/30 bg-amber/8 px-4 py-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-amber whitespace-nowrap transition-colors hover:bg-amber/15 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-amber/8"
            >
              Save as overlay
            </button>
          </>
        )}
      </div>
    </div>
  );
}
