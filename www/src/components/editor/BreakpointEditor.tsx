import { useState } from "react";
import { useMeta } from "../../hooks/useMeta";
import { UNKNOWN_CWD, useOverlaysStore } from "../../stores/overlaysStore";
import { useUIStore } from "../../stores/uiStore";
import type { PausedFlow } from "../../types";

import { useBreakpointEditorActions } from "./BreakpointEditorActions";
import { BreakpointEditorPanes } from "./BreakpointEditorPanes";
import { BreakpointEditorTabs, type EditorViewMode } from "./BreakpointEditorTabs";
import { DismissablePanel } from "./DismissablePanel";
import { EditorActions } from "./EditorActions";
import { PausedHeader } from "./PausedHeader";

interface BreakpointEditorProps {
  pausedFlow: PausedFlow;
  onResolved: () => void;
}

export function BreakpointEditor({ pausedFlow, onResolved }: BreakpointEditorProps) {
  const [viewMode, setViewMode] = useState<EditorViewMode>("messages");
  const createDraft = useOverlaysStore((s) => s.createDraft);
  const setActiveRoute = useUIStore((s) => s.setActiveRoute);
  const { meta } = useMeta();
  const {
    editedIr,
    audit,
    overrides,
    overridesEnabled,
    loading,
    error,
    handleUpsert,
    handleToggle,
    handleClear,
    handleForward,
    handleForwardUnmodified,
    handleDrop,
  } = useBreakpointEditorActions({ pausedFlow, onResolved });

  const handleSaveAsOverlay = () => {
    if (overrides.length === 0) return;
    // Prefetched at app mount, so `meta.cwd` is typically warm by the
    // time this fires. The UNKNOWN_CWD fallback covers the rare cold
    // click; OverlaysView rehydrates the placeholder once meta lands.
    createDraft(overrides, { kind: "project", cwd: meta?.cwd ?? UNKNOWN_CWD });
    setActiveRoute("overlays");
  };

  return (
    <div className="flex h-full flex-col">
      <PausedHeader
        flowId={pausedFlow.flow_id}
        pausedAtMs={pausedFlow.paused_at_ms}
        provider={pausedFlow.ir.provider}
        model={editedIr.model}
        tokensBefore={pausedFlow.tokens_before}
      />
      {error && (
        <p className="mx-5 mt-3 border border-rose/25 bg-rose/5 px-4 py-2.5 text-[13px] text-rose">
          {error}
        </p>
      )}

      <EditorActions
        originalIr={pausedFlow.ir}
        audit={audit}
        editedIr={editedIr}
        overridesEnabled={overridesEnabled}
        onToggleOverrides={handleToggle}
        onClearOverrides={handleClear}
        onForward={handleForward}
        onForwardUnmodified={handleForwardUnmodified}
        onDrop={handleDrop}
        overridesCount={overrides.length}
        loading={loading}
      />

      {/* One-time notices. Both sit above the tab bar so the reader
          absorbs the framing (what this pane does, why the numbers look
          the way they do) before committing to a tab. Dismissal persists
          in localStorage under a stable key, so returning users see
          neither panel again. */}
      <DismissablePanel id="editor.tampering" tone="warn" title="Editing a live API request">
        The provider treats your edits as the authoritative payload and logs the modified version.
        Aggressive changes to system prompts or built-in tools can return no response from the API.
      </DismissablePanel>
      <DismissablePanel
        id="editor.chars-vs-tokens"
        tone="info"
        title="Line items are character counts"
      >
        Per-override, per-category, and per-block counts are characters because they're precise,
        consistent, and cost no extra API calls. Real token counts appear only where the provider
        reports them: the header readout, the response breakdown, and pipeline totals on completed
        exchanges.
      </DismissablePanel>

      <BreakpointEditorTabs
        viewMode={viewMode}
        overridesCount={overrides.length}
        loading={loading}
        onViewModeChange={setViewMode}
        onSaveAsOverlay={handleSaveAsOverlay}
      />
      <BreakpointEditorPanes
        viewMode={viewMode}
        pausedFlow={pausedFlow}
        editedIr={editedIr}
        overrides={overrides}
        onOverride={handleUpsert}
      />
    </div>
  );
}
