import { type ReactElement, useCallback, useEffect, useState } from "react";
import type { HarnessName } from "../../../types";
import { useCapturedRunStore } from "../../model/capturedRunStore";
import { harnessLabel } from "../../model/paneRecords";
import { parseRunErrorFrame, type RunErrorFrame } from "./runTerminalFrames";
import { closedMessage, useTerminalSession } from "./terminalSession";
import { runTerminalSocketUrl } from "./terminalSocket";
import "./terminal-pane.css";

export interface CapturedRunPaneProps {
  /** Stable per-pane key (the lab pane id) that owns this run; the persistence key. */
  runKey: string;
  /** Managed harness to launch as a captured run; selects the terminal and harness label. */
  provider: HarnessName;
  /** Absolute working directory; omitted lets the backend resolve its workspace. */
  cwd?: string;
}

/**
 * A captured managed harness session (Claude or Codex) in a canvas pane: the desktop
 * equivalent of `transport-matters {provider}`, with the agent's traffic routed
 * through the TM reverse proxy. Each pane owns its OWN server-managed run, keyed by
 * `runKey` (the stable pane id): it spawns the run once via `POST /v1/runs`,
 * persists the `runId` under its key, and attaches its terminal over a WebSocket, so
 * two same-provider panes never share a PTY. A browser reload re-attaches the same
 * run (output continues) instead of re-spawning; a transient socket drop detaches
 * but leaves the run running. The pane reads as a plain terminal surface (its
 * captured identity is the window title); a spawn failure or an inbound run.error
 * frame surfaces as an alert banner.
 */
export function CapturedRunPane({ runKey, provider, cwd }: CapturedRunPaneProps): ReactElement {
  const ensureRun = useCapturedRunStore((state) => state.ensureRun);
  const persistedRunId = useCapturedRunStore((state) => state.runs[runKey]?.runId);
  const oscColorReplies = useCapturedRunStore((state) => state.oscColorReplies);
  // Seed from the persisted run so a reload attaches on the first render (no
  // loading flash and no re-spawn); ensureRun still runs to spawn the first time.
  const [runId, setRunId] = useState<string | null>(persistedRunId ?? null);
  const [spawnError, setSpawnError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    ensureRun(runKey, provider, cwd, oscColorReplies).then(
      (id) => {
        if (!cancelled) setRunId(id);
      },
      (error: unknown) => {
        if (!cancelled) setSpawnError(spawnErrorMessage(provider, error));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [ensureRun, runKey, provider, cwd, oscColorReplies]);

  if (spawnError !== null) {
    return (
      <div className="terminal-pane">
        <p className="terminal-pane__status" role="alert">
          {spawnError}
        </p>
      </div>
    );
  }
  if (runId === null) {
    return (
      <div className="terminal-pane" aria-busy="true">
        <p className="terminal-pane__status terminal-pane__status--progress" role="status">
          Starting {harnessLabel(provider)}…
        </p>
      </div>
    );
  }
  return <AttachedRunTerminal paneId={runKey} provider={provider} runId={runId} />;
}

/** Attach the shared terminal session core to an already-spawned run's PTY. */
function AttachedRunTerminal({
  paneId,
  provider,
  runId,
}: {
  paneId: string;
  provider: HarnessName;
  runId: string;
}): ReactElement {
  const [errorFrame, setErrorFrame] = useState<RunErrorFrame | null>(null);
  const [hasOutput, setHasOutput] = useState(false);

  const buildUrl = useCallback(
    (cols: number, rows: number) => runTerminalSocketUrl(runId, cols, rows),
    [runId],
  );
  // The ready/scrollback frames are informational (the window title is the only
  // chrome); only an inbound run.error needs to surface as a banner.
  const onTextFrame = useCallback((text: string) => {
    const frame = parseRunErrorFrame(text);
    if (frame) setErrorFrame(frame);
  }, []);
  const onOutput = useCallback(() => setHasOutput(true), []);

  const { surfaceRef, closedCode } = useTerminalSession({
    buildUrl,
    onOutput,
    onTextFrame,
    paneId,
    suppressColorQueryReplies: true,
  });
  const status = runStatus(provider, errorFrame, closedCode);

  return (
    <div className="terminal-pane">
      <div className="terminal-pane__surface" ref={surfaceRef} />
      {status === null ? null : (
        <p className="terminal-pane__status" role="alert">
          {status}
        </p>
      )}
      {status === null && !hasOutput ? (
        <p className="terminal-pane__status terminal-pane__status--progress" role="status">
          Starting {harnessLabel(provider)}…
        </p>
      ) : null}
    </div>
  );
}

/** A run.error frame wins over a plain socket close; both surface as a banner. */
function runStatus(
  provider: HarnessName,
  error: RunErrorFrame | null,
  closedCode: number | null,
): string | null {
  if (error) return `Captured run failed (${error.code}): ${error.message}`;
  if (closedCode !== null) return closedMessage(closedCode, harnessLabel(provider));
  return null;
}

function spawnErrorMessage(provider: HarnessName, error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  return `${harnessLabel(provider)} captured run failed to start: ${detail}`;
}
