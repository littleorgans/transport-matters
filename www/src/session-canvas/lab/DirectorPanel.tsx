import { type ReactElement, useCallback, useEffect, useState } from "react";
import { deleteRun, listRuns, type RunView } from "../../api";
import { cliLabel } from "../model/paneRecords";
import { useCanvasLabStore } from "./canvasLabStore";

/**
 * Director surface (lab): a live roster of managed captured runs. It GETs `/api/runs` on
 * mount and on manual refresh, and lets an operator attach to a listed run or stop it.
 *
 * Attach binds a pane to the run's EXISTING run id (open/restore — never a re-spawn), so
 * the operator can pick up a running agent they have no pane for; the viewer count ticks
 * up rather than a second run starting. Stop DELETEs the run and drops it from the list.
 * Closing a pane only detaches (the run stays listed, its viewer count drops). The surface
 * is lab-isolated: it reuses the captured-run store and never leaks into production
 * canvases.
 */
export function DirectorPanel(): ReactElement {
  const attachCapturedRun = useCanvasLabStore((state) => state.attachCapturedRun);
  const [runs, setRuns] = useState<RunView[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState<ReadonlySet<string>>(() => new Set<string>());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setRuns(await listRuns());
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  // GET the roster on mount (and whenever the command bar remounts it).
  useEffect(() => {
    void refresh();
  }, [refresh]);

  const stop = useCallback(
    async (runId: string) => {
      setStopping((prev) => new Set(prev).add(runId));
      try {
        await deleteRun(runId);
        await refresh();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setStopping((prev) => {
          const next = new Set(prev);
          next.delete(runId);
          return next;
        });
      }
    },
    [refresh],
  );

  return (
    <section aria-label="Live captured runs" className="canvas-lab-director">
      <header className="canvas-lab-director__head">
        <span className="canvas-lab-director__title">Live runs</span>
        <span className="canvas-lab-director__count">{runs.length}</span>
        <button
          className="canvas-button"
          disabled={loading}
          onClick={() => void refresh()}
          type="button"
        >
          Refresh
        </button>
      </header>
      {error !== null ? (
        <p className="canvas-lab-director__status" role="alert">
          {error}
        </p>
      ) : null}
      {error === null && runs.length === 0 ? (
        <p className="canvas-lab-director__status">{loading ? "Loading runs…" : "No live runs."}</p>
      ) : null}
      {runs.length > 0 ? (
        <ul className="canvas-lab-director__list">
          {runs.map((run) => (
            <li className="canvas-lab-director__row" key={run.runId}>
              <span className="canvas-lab-director__cli">{cliLabel(run.cli)}</span>
              <span className="canvas-lab-director__state" data-state={run.state}>
                {run.state}
              </span>
              <span className="canvas-lab-director__cwd" title={run.cwd}>
                {run.cwd}
              </span>
              <span className="canvas-lab-director__viewers">
                {run.viewerCount} {run.viewerCount === 1 ? "viewer" : "viewers"}
              </span>
              <span className="canvas-lab-director__actions">
                <button
                  className="canvas-button"
                  onClick={() => attachCapturedRun(run.cli, run.runId)}
                  type="button"
                >
                  Attach
                </button>
                <button
                  className="canvas-button"
                  disabled={stopping.has(run.runId)}
                  onClick={() => void stop(run.runId)}
                  type="button"
                >
                  Stop
                </button>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
