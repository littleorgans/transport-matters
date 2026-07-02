import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import {
  armBreakpoint,
  disarmBreakpoint,
  fetchBreakpointStatus,
  fetchPausedFlowDetail,
} from "../api";
import { useUIStore } from "../stores/uiStore";
import type { BreakpointStatusDetail } from "../types";

export function useBreakpoint(): {
  mode: "off" | "armed_once";
  arm: () => Promise<void>;
  disarm: () => Promise<void>;
  error: Error | null;
} {
  const queryClient = useQueryClient();
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const pausedFlow = useUIStore((s) => s.pausedFlow);

  const { data, error } = useQuery({
    queryKey: ["breakpoint-status"],
    queryFn: fetchBreakpointStatus,
  });

  // Hydrate pausedFlow from status on mount — handles browser refresh mid-pause,
  // where the SSE "paused" event has already been missed.
  const pausedFlows = data?.paused_flows;
  useEffect(() => {
    if (!pausedFlows?.length || pausedFlow) return;
    const first = pausedFlows[0];
    if (!first) return;
    fetchPausedFlowDetail(first.flow_id)
      .then(setPausedFlow)
      .catch((err) => console.error("Failed to hydrate paused flow:", err));
  }, [pausedFlows, pausedFlow, setPausedFlow]);

  const armMutation = useMutation({
    mutationFn: armBreakpoint,
    onSuccess: () =>
      queryClient.setQueryData<BreakpointStatusDetail>(["breakpoint-status"], (prev) => ({
        mode: "armed_once",
        paused_flows: prev?.paused_flows ?? [],
      })),
  });

  const disarmMutation = useMutation({
    mutationFn: disarmBreakpoint,
    onSuccess: () =>
      queryClient.setQueryData<BreakpointStatusDetail>(["breakpoint-status"], (prev) => ({
        mode: "off",
        paused_flows: prev?.paused_flows ?? [],
      })),
  });

  return {
    mode: data?.mode ?? "off",
    arm: () => armMutation.mutateAsync(),
    disarm: () => disarmMutation.mutateAsync(),
    error: error instanceof Error ? error : null,
  };
}
