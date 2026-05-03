import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { dropFlow, reauditFlow, releaseFlow, releaseFlowUnmodified } from "../../api";
import { useOverrides } from "../../hooks/useOverrides";
import { useUIStore } from "../../stores/uiStore";
import type { InternalRequest, Override, OverrideAudit, PausedFlow } from "../../types";

interface UseBreakpointEditorActionsOptions {
  pausedFlow: PausedFlow;
  onResolved: () => void;
}

interface ReleasedFlowCompletion {
  shouldWaitForStream: boolean;
  selectedId: string | null;
}

interface UseBreakpointEditorActionsResult {
  editedIr: InternalRequest;
  audit: OverrideAudit | null;
  overrides: Override[];
  overridesEnabled: boolean;
  loading: boolean;
  error: string | null;
  handleUpsert: (batch: Override[]) => void;
  handleToggle: () => void;
  handleClear: () => void;
  handleForward: () => void;
  handleForwardUnmodified: () => void;
  handleDrop: () => void;
}

export function getExchangeDetailQueryKey(pausedFlow: PausedFlow): readonly ["exchange", string] {
  return ["exchange", pausedFlow.provisional_exchange_id ?? pausedFlow.flow_id];
}

export function getReleasedFlowCompletion(pausedFlow: PausedFlow): ReleasedFlowCompletion {
  if (pausedFlow.transport === "websocket") {
    return {
      shouldWaitForStream: false,
      selectedId: pausedFlow.provisional_exchange_id ?? null,
    };
  }
  return { shouldWaitForStream: true, selectedId: null };
}

export function useBreakpointEditorActions({
  pausedFlow,
  onResolved,
}: UseBreakpointEditorActionsOptions): UseBreakpointEditorActionsResult {
  const queryClient = useQueryClient();
  const setForwardingFlowId = useUIStore((s) => s.setForwardingFlowId);
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const setSelectedId = useUIStore((s) => s.setSelectedId);
  const forwardingFlowId = useUIStore((s) => s.forwardingFlowId);
  const forwardingLastActivityAt = useUIStore((s) => s.forwardingLastActivityAt);
  const [editedIr, setEditedIr] = useState<InternalRequest>(() => structuredClone(pausedFlow.ir));
  const [audit, setAudit] = useState<OverrideAudit | null>(pausedFlow.audit);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const overrideScope = useMemo(
    () => ({
      run_id: pausedFlow.run_id ?? null,
      track_id: pausedFlow.track_id ?? pausedFlow.run_id ?? null,
    }),
    [pausedFlow.run_id, pausedFlow.track_id],
  );
  const { overrides, enabled, upsert, clear, toggle } = useOverrides(overrideScope);

  // Each activity stamp restarts the silence window for the active forward.
  // biome-ignore lint/correctness/useExhaustiveDependencies: forwardingLastActivityAt is an intentional subscription trigger
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

  const withLoading = useCallback(async (label: string, fn: () => Promise<void>) => {
    setError(null);
    setLoading(true);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} failed`);
      setLoading(false);
    }
  }, []);

  const handleUpsert = useCallback(
    (batch: Override[]) =>
      void withError("Override update", async () => {
        const resp = await upsert(batch);
        if (resp.audit) setAudit(resp.audit);
        if (resp.curated_ir) setEditedIr(resp.curated_ir);
      }),
    [upsert, withError],
  );

  const handleToggle = useCallback(
    () =>
      void withError("Toggle", async () => {
        const resp = await toggle();
        if (resp.audit) setAudit(resp.audit);
        if (resp.curated_ir) setEditedIr(resp.curated_ir);
      }),
    [toggle, withError],
  );

  const handleClear = useCallback(
    () =>
      void withError("Clear", async () => {
        await clear();
        const result = await reauditFlow(pausedFlow.flow_id);
        setAudit(result.audit);
        setEditedIr(result.curated_ir);
        setPausedFlow({ ...pausedFlow, tokens_before: result.tokens_before });
      }),
    [clear, pausedFlow, setPausedFlow, withError],
  );

  const invalidateExchange = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: getExchangeDetailQueryKey(pausedFlow) });
  }, [pausedFlow, queryClient]);

  const completeReleasedFlow = useCallback(() => {
    const completion = getReleasedFlowCompletion(pausedFlow);
    if (completion.shouldWaitForStream) {
      setForwardingFlowId(pausedFlow.flow_id);
      return;
    }
    if (completion.selectedId) {
      setSelectedId(completion.selectedId);
    }
    onResolved();
  }, [onResolved, pausedFlow, setForwardingFlowId, setSelectedId]);

  const handleForward = useCallback(
    () =>
      void withLoading("Forward", async () => {
        await releaseFlow(pausedFlow.flow_id, editedIr);
        invalidateExchange();
        completeReleasedFlow();
      }),
    [completeReleasedFlow, editedIr, invalidateExchange, pausedFlow.flow_id, withLoading],
  );

  const handleForwardUnmodified = useCallback(
    () =>
      void withLoading("Pass through", async () => {
        await releaseFlowUnmodified(pausedFlow.flow_id);
        invalidateExchange();
        completeReleasedFlow();
      }),
    [completeReleasedFlow, invalidateExchange, pausedFlow.flow_id, withLoading],
  );

  const handleDrop = useCallback(
    () =>
      void withLoading("Drop", async () => {
        await dropFlow(pausedFlow.flow_id);
        invalidateExchange();
        onResolved();
      }),
    [invalidateExchange, onResolved, pausedFlow.flow_id, withLoading],
  );

  return {
    editedIr,
    audit,
    overrides,
    overridesEnabled: enabled,
    loading,
    error,
    handleUpsert,
    handleToggle,
    handleClear,
    handleForward,
    handleForwardUnmodified,
    handleDrop,
  };
}
