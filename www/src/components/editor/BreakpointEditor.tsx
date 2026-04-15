import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { dropFlow, reauditFlow, releaseFlow, releaseFlowUnmodified } from "../../api";
import { useMeta } from "../../hooks/useMeta";
import { useOverrides } from "../../hooks/useOverrides";
import { UNKNOWN_CWD, useOverlaysStore } from "../../stores/overlaysStore";
import { useUIStore } from "../../stores/uiStore";
import type { InternalRequest, Override, OverrideAudit, PausedFlow } from "../../types";

import { JsonView } from "../detail/JsonView";
import { DismissablePanel } from "./DismissablePanel";
import { EditorActions } from "./EditorActions";
import { GlobalSection } from "./GlobalSection";
import { MessagesSection } from "./MessagesSection";
import { PausedHeader } from "./PausedHeader";
import { SamplingSection } from "./SamplingSection";
import { SystemSection } from "./SystemSection";
import { ToolsSection } from "./ToolsSection";

type ViewMode = "messages" | "overlay" | "raw";

const TAB_ORDER: ViewMode[] = ["messages", "overlay", "raw"];

interface BreakpointEditorProps {
  pausedFlow: PausedFlow;
  onResolved: () => void;
}

export function BreakpointEditor({ pausedFlow, onResolved }: BreakpointEditorProps) {
  const queryClient = useQueryClient();
  const setForwardingFlowId = useUIStore((s) => s.setForwardingFlowId);
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const forwardingFlowId = useUIStore((s) => s.forwardingFlowId);
  const forwardingLastActivityAt = useUIStore((s) => s.forwardingLastActivityAt);
  const [editedIr, setEditedIr] = useState<InternalRequest>(() => structuredClone(pausedFlow.ir));
  const [audit, setAudit] = useState<OverrideAudit | null>(pausedFlow.audit);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("messages");
  const { overrides, enabled, upsert, clear, toggle } = useOverrides();
  const createDraft = useOverlaysStore((s) => s.createDraft);
  const setActiveRoute = useUIStore((s) => s.setActiveRoute);
  const { meta } = useMeta();

  const handleSaveAsOverlay = () => {
    if (overrides.length === 0) return;
    // Prefetched at app mount, so `meta.cwd` is typically warm by the
    // time this fires. The UNKNOWN_CWD fallback covers the rare cold
    // click; OverlaysView rehydrates the placeholder once meta lands.
    createDraft(overrides, { kind: "project", cwd: meta?.cwd ?? UNKNOWN_CWD });
    setActiveRoute("overlays");
  };

  // Silence-window forward timeout. Each SSE event carrying the
  // forwarding flow's id stamps `forwardingLastActivityAt` in the
  // store, which re-runs this effect and restarts the 120s clock. The
  // banner only fires after 120s of total upstream silence, so long
  // thinking + tool-use chains no longer trip a false timeout.
  //
  // `forwardingLastActivityAt` is a dependency we never read inside
  // the effect — its value does not influence the timer math, only a
  // change in it triggers the re-subscription. The biome-ignore keeps
  // the lint rule from pruning it and breaking the liveness pattern.
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional re-subscription trigger
  useEffect(() => {
    if (!forwardingFlowId) return;
    const timer = setTimeout(() => {
      setForwardingFlowId(null);
      setLoading(false);
      setError("Forward timed out. The response never arrived. You can retry.");
    }, 120_000);
    return () => clearTimeout(timer);
  }, [forwardingFlowId, forwardingLastActivityAt, setForwardingFlowId]);

  const withError = useCallback(async (label: string, fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} failed`);
    }
  }, []);

  const withLoading = async (label: string, fn: () => Promise<void>) => {
    setError(null);
    setLoading(true);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} failed`);
      setLoading(false);
    }
  };

  const handleUpsert = useCallback(
    (batch: Override[]) =>
      withError("Override update", async () => {
        const resp = await upsert(batch);
        if (resp.audit) setAudit(resp.audit);
        if (resp.curated_ir) setEditedIr(resp.curated_ir);
      }),
    [upsert, withError],
  );

  const handleToggle = useCallback(
    () =>
      withError("Toggle", async () => {
        const resp = await toggle();
        if (resp.audit) setAudit(resp.audit);
        if (resp.curated_ir) setEditedIr(resp.curated_ir);
      }),
    [toggle, withError],
  );

  const handleClear = useCallback(
    () =>
      withError("Clear", async () => {
        await clear();
        const result = await reauditFlow(pausedFlow.flow_id);
        setAudit(result.audit);
        setEditedIr(result.curated_ir);
        // Re-audit recounts tokens on the server; propagate so the
        // header's Tokens readout tracks the new curated IR instead
        // of stale pre-clear counts.
        setPausedFlow({ ...pausedFlow, tokens_before: result.tokens_before });
      }),
    [clear, pausedFlow, setPausedFlow, withError],
  );

  const invalidateExchange = () => {
    void queryClient.invalidateQueries({ queryKey: ["exchange", pausedFlow.flow_id] });
  };

  const handleForward = () =>
    withLoading("Forward", async () => {
      await releaseFlow(pausedFlow.flow_id, editedIr);
      invalidateExchange();
      setForwardingFlowId(pausedFlow.flow_id);
    });

  const handleForwardUnmodified = () =>
    withLoading("Pass through", async () => {
      await releaseFlowUnmodified(pausedFlow.flow_id);
      invalidateExchange();
      setForwardingFlowId(pausedFlow.flow_id);
    });

  const handleDrop = () =>
    withLoading("Drop", async () => {
      await dropFlow(pausedFlow.flow_id);
      invalidateExchange();
      onResolved();
    });

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
        overridesEnabled={enabled}
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

      {/* Tab bar — three semantic lenses on the same paused flow.
          MESSAGES is the per-call payload (global strip + the message
          stream). OVERLAY is the durable session shape (sampling +
          system + tools). RAW shows the edited IR as JSON. A
          right-anchored slot on the same row hosts SAVE AS OVERLAY,
          surfaced only when OVERLAY is active so it reads as the
          commit action for the tab the user is on. */}
      <div className="flex items-stretch border-y border-edge">
        {TAB_ORDER.map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => setViewMode(mode)}
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
                {overrides.length === 0
                  ? "Make an override to save as an overlay"
                  : `${overrides.length} override${overrides.length !== 1 ? "s" : ""} ready to lift`}
              </span>
              <button
                type="button"
                disabled={loading || overrides.length === 0}
                onClick={handleSaveAsOverlay}
                className="btn cursor-pointer border border-amber/30 bg-amber/8 px-4 py-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-amber whitespace-nowrap transition-colors hover:bg-amber/15 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-amber/8"
              >
                Save as overlay
              </button>
            </>
          )}
        </div>
      </div>

      {viewMode === "raw" && (
        /* Raw — reuse the virtualized JsonView so the edited IR renders
           with the same colorized, copy-able treatment as REQUEST and
           RESPONSE in the detail view. JsonView handles its own scroll,
           padding, and line-count strip. */
        <div className="flex-1 overflow-y-auto">
          <JsonView payload={editedIr} />
        </div>
      )}

      {viewMode === "messages" && (
        <div className="flex-1 overflow-y-auto px-8 py-7 space-y-8">
          <GlobalSection
            messages={pausedFlow.original_messages ?? pausedFlow.ir.messages}
            overrides={overrides}
            onOverride={handleUpsert}
          />
          <MessagesSection
            messages={pausedFlow.original_messages ?? pausedFlow.ir.messages}
            overrides={overrides}
            onOverride={handleUpsert}
          />
          <div className="h-8" />
        </div>
      )}

      {viewMode === "overlay" && (
        <div className="flex-1 overflow-y-auto px-8 py-7 space-y-8">
          <SamplingSection
            sampling={editedIr.sampling}
            originalSampling={pausedFlow.original_sampling}
            providerExtras={editedIr.provider_extras}
            originalProviderExtras={pausedFlow.original_provider_extras}
            overrides={overrides}
            onOverride={handleUpsert}
          />
          <SystemSection
            parts={pausedFlow.original_system ?? pausedFlow.ir.system}
            overrides={overrides}
            onOverride={handleUpsert}
          />
          <ToolsSection
            tools={pausedFlow.original_tools}
            overrides={overrides}
            onOverride={handleUpsert}
          />
          <div className="h-8" />
        </div>
      )}
    </div>
  );
}
