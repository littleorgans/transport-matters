import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { armBreakpoint, disarmBreakpoint, fetchBreakpointStatus } from "../api";

export function useBreakpoint(): {
  mode: "off" | "armed_once";
  arm: () => Promise<void>;
  disarm: () => Promise<void>;
} {
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["breakpoint-status"],
    queryFn: fetchBreakpointStatus,
  });

  const armMutation = useMutation({
    mutationFn: armBreakpoint,
    onSuccess: () => queryClient.setQueryData(["breakpoint-status"], { mode: "armed_once" }),
  });

  const disarmMutation = useMutation({
    mutationFn: disarmBreakpoint,
    onSuccess: () => queryClient.setQueryData(["breakpoint-status"], { mode: "off" }),
  });

  return {
    mode: data?.mode ?? "off",
    arm: () => armMutation.mutateAsync(),
    disarm: () => disarmMutation.mutateAsync(),
  };
}
