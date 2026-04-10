import { useCallback, useEffect, useState } from "react";
import {
  armBreakpoint,
  disarmBreakpoint,
  dropFlow,
  fetchBreakpointStatus,
  releaseFlow,
} from "../api";
import type { InternalRequest } from "../types";

export function useBreakpoint(): {
  mode: "off" | "armed_once";
  arm: () => Promise<void>;
  disarm: () => Promise<void>;
  forward: (flowId: string, ir: InternalRequest) => Promise<void>;
  drop: (flowId: string) => Promise<void>;
} {
  const [mode, setMode] = useState<"off" | "armed_once">("off");

  useEffect(() => {
    fetchBreakpointStatus()
      .then((s) => setMode(s.mode))
      .catch(() => {});
  }, []);

  const arm = useCallback(async () => {
    await armBreakpoint();
    setMode("armed_once");
  }, []);

  const disarm = useCallback(async () => {
    await disarmBreakpoint();
    setMode("off");
  }, []);

  const forward = useCallback(async (flowId: string, ir: InternalRequest) => {
    await releaseFlow(flowId, ir);
  }, []);

  const drop = useCallback(async (flowId: string) => {
    await dropFlow(flowId);
  }, []);

  return { mode, arm, disarm, forward, drop };
}
