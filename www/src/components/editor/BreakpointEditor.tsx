import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { dropFlow, reauditFlow, releaseFlow, releaseFlowUnmodified } from "../../api";
import { useOverrides } from "../../hooks/useOverrides";
import { useUIStore } from "../../stores/uiStore";
import type {
  InternalRequest,
  Override,
  OverrideAudit,
  PausedFlow,
  SamplingParams,
} from "../../types";

import { JsonView } from "../detail/JsonView";
import { DismissablePanel } from "./DismissablePanel";
import { EditorActions } from "./EditorActions";
import { MessagesSection } from "./MessagesSection";
import { PausedHeader } from "./PausedHeader";
import { SamplingSection } from "./SamplingSection";
import { SystemSection } from "./SystemSection";
import { ToolsSection } from "./ToolsSection";

interface BreakpointEditorProps {
  pausedFlow: PausedFlow;
  onResolved: () => void;
}

export function BreakpointEditor({ pausedFlow, onResolved }: BreakpointEditorProps) {
  const queryClient = useQueryClient();
  const setForwardingFlowId = useUIStore((s) => s.setForwardingFlowId);
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const forwardingFlowId = useUIStore((s) => s.forwardingFlowId);
  const [editedIr, setEditedIr] = useState<InternalRequest>(() => structuredClone(pausedFlow.ir));
  const [audit, setAudit] = useState<OverrideAudit | null>(pausedFlow.audit);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"form" | "raw">("form");
  const { overrides, enabled, upsert, clear, toggle } = useOverrides();

  const setSampling = (sampling: SamplingParams) => setEditedIr((ir) => ({ ...ir, sampling }));
  const setProviderExtras = (provider_extras: Record<string, unknown>) =>
    setEditedIr((ir) => ({ ...ir, provider_extras }));

  // Reset forwarding state if the SSE exchange event never arrives
  useEffect(() => {
    if (!forwardingFlowId) return;
    const timer = setTimeout(() => {
      setForwardingFlowId(null);
      setLoading(false);
      setError("Forward timed out. The response never arrived. You can retry.");
    }, 45_000);
    return () => clearTimeout(timer);
  }, [forwardingFlowId, setForwardingFlowId]);

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
        overrides={overrides}
        overridesEnabled={enabled}
        onToggleOverrides={handleToggle}
        onClearOverrides={handleClear}
        onForward={handleForward}
        onForwardUnmodified={handleForwardUnmodified}
        onDrop={handleDrop}
        loading={loading}
      />

      {/* View mode tab bar — pressed-key sibling of the detail view's
          INSPECT|REQUEST|RESPONSE bar. Lives directly above the
          content it switches so the choice is visually bound to what
          renders below. Pulled out of the action strip to keep that
          row focused purely on decide-what-to-do-next. */}
      <div className="flex border-y border-edge">
        {(["form", "raw"] as const).map((mode) => (
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
        <div className="flex-1 tab-rest" />
      </div>

      {/* One-time notices. Both sit above the action strip so the reader
          absorbs the framing (what this pane does, why the numbers look
          the way they do) before pressing Forward. Dismissal persists in
          localStorage under a stable key, so returning users see neither
          panel again. */}
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

      {viewMode === "raw" ? (
        /* Raw — reuse the virtualized JsonView so the edited IR renders
           with the same colorized, copy-able treatment as REQUEST and
           RESPONSE in the detail view. JsonView handles its own scroll,
           padding, and line-count strip. */
        <div className="flex-1 overflow-y-auto">
          <JsonView payload={editedIr} />
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-8 py-7 space-y-8">
          <SamplingSection
            sampling={editedIr.sampling}
            onChange={setSampling}
            providerExtras={editedIr.provider_extras}
            onProviderExtrasChange={setProviderExtras}
          />
          <MessagesSection
            messages={pausedFlow.original_messages ?? pausedFlow.ir.messages}
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
