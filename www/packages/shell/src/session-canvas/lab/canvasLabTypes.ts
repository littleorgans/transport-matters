import type { HarnessName } from "@tm/core/types/capabilities";
import type {
  CanvasViewport,
  EngineLayoutState,
  PaneId,
  ViewportBounds,
  WorldRect,
} from "../../engine";
import type { LayoutParams, ParamValue } from "../../engine/layout";
import type { FramingState } from "../model/paneAffordances";
import type { DockedPane, PaneContentRef } from "../model/paneRecords";

export interface CanvasLabState {
  layout: EngineLayoutState;
  bounds: ViewportBounds;
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  /**
   * The legibility experiment's winner (Stuart, 2026-06-13): a glyph halo that
   * keeps terminal text crisp over bright scenes while leaving the scene
   * visible. A scrim variant measured better on WCAG area contrast but lost
   * the comparison by repainting the default look over the theme.
   */
  textShadow: boolean;
  framing: FramingState;
  expandedPaneId: PaneId | null;
  flying: boolean;
  paneMotion: boolean;
  nextPaneIndex: number;
  spaceId: string | null;
  defaultWorktreeId: string | null;
  /** Real content per pane (a viewer-registry ref). Demo card/ruler panes carry none. */
  contentRefs: Record<PaneId, PaneContentRef>;
  /** Locally minimized panes for THIS canvas, most-recent first. The dock's only source. */
  docked: DockedPane[];
  /** Monotonic per-label-prefix counters so spawned content panes get incremental names
   *  (Terminal-1, Claude-2, Codex-3) like demo panes get lab-N. Never reused on close. */
  paneCounters: Record<string, number>;
  addPane(): void;
  addTerminal(): void;
  addCapturedRun(provider: HarnessName): void;
  adoptDefaultWorktree(spaceId: string | null, worktreeId: string): void;
  setDefaultWorktree(spaceId: string | null, worktreeId: string): void;
  /** Open (or focus/restore) a content pane at its registry pane id. Used by canvas file drops. */
  spawnPane(ref: PaneContentRef, options?: { focus?: boolean }): PaneId;
  /** Minimize ([-]): park the pane in the dock and remove it. Generic, runs the kind's onMinimize hook (captured keeps its run alive). */
  minimizePane(paneId: PaneId): void;
  /** Close ([X]): remove the pane and run the kind's onClose hook (captured-run kills the run via POST /terminate). */
  closePane(paneId: PaneId): void;
  /** Restore a docked pane: re-seed it at its original id so its viewer re-mounts (captured re-attaches by run id). */
  restorePane(paneId: PaneId): void;
  /** Dock drag-out (doc 18): the same restore, spliced to the order slot the drop point chose. */
  restorePaneAtIndex(paneId: PaneId, index: number): void;
  /** Close/kill a docked pane WITHOUT restoring it: run its onClose hook (captured-run kills the run) and drop the dock entry. */
  closeDockedPane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  updatePaneRect(paneId: PaneId, rect: WorldRect): void;
  setStrategy(strategyId: string): void;
  setParam(key: string, value: ParamValue): void;
  setFitToContent(on: boolean): void;
  setTextShadow(on: boolean): void;
  setOscColorReplies(on: boolean): void;
  organize(): void;
  /** Terminal delivery: park a ref straight into the dock, no pane, no replan. Open panes minimize. */
  dockPane(ref: PaneContentRef): PaneId;
  /** Release: splice the order and replan. */
  commitReorder(paneId: PaneId, index: number): void;
  setBounds(bounds: ViewportBounds): void;
  expandPane(paneId: PaneId): void;
  unexpand(): void;
  framePane(paneId: PaneId): void;
  unframe(): void;
  resetView(): void;
  setViewport(viewport: CanvasViewport): void;
}
