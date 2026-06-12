import type { CanvasViewport } from "./engine/viewport.ts";

/**
 * The transplant contract. `createAmbientBackground` and everything under
 * src/ambient/ is framework-agnostic vanilla TS: in production it mounts as a
 * <canvas> underlay inside `.canvas-viewport`, behind `.canvas-world`, and the
 * React layer simply forwards `layout.viewport` to setViewport and app/agent
 * state to setSignal. Nothing in here may import from the lab harness.
 */
/**
 * Agent activity states the background reacts to:
 * idle — nothing running; working — agent is producing; waiting — the agent
 * is waiting on you (held turn, question, approval); error — fault.
 */
export type AmbientSignalState = "idle" | "working" | "waiting" | "error";

export interface AmbientSignal {
  state: AmbientSignalState;
  /** 0..1 — how much presence the background is allowed to have right now. */
  intensity: number;
}

export const AMBIENT_STATE_INDEX: Record<AmbientSignalState, number> = {
  idle: 0,
  working: 1,
  waiting: 2,
  error: 3,
};

export interface AmbientSceneParam {
  id: string;
  /** Fragment renderer bridge. Theme JSON keys params by id, never by uniform. */
  uniform?: string;
  label: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
}

export interface AmbientSceneBase {
  id: string;
  label: string;
  /** One-line description shown on the scene card. */
  description?: string;
  /** Contextual controls this scene exposes. */
  params?: readonly AmbientSceneParam[];
  /** Scene samples the shared photo texture (uPhotoTex/uPhotoAspect/uPhotoReady). */
  usesPhoto?: boolean;
}

export interface AmbientFragmentSceneDefinition extends AmbientSceneBase {
  kind: "fragment";
  /** Fragment shader; must begin with the shared scene prelude. */
  fragmentShaderSource: string;
}

export interface AmbientModuleSceneDefinition extends AmbientSceneBase {
  kind: "module";
  /** Versioned module scene code known to the registry, never serialized by themes. */
  moduleId: string;
}

export type AmbientSceneDefinition = AmbientFragmentSceneDefinition | AmbientModuleSceneDefinition;

export interface AmbientModuleSceneInput {
  sceneId: string;
  sceneParams: Readonly<Record<string, number>>;
  photoKey?: string;
}

export interface AmbientBackground {
  setViewport(viewport: CanvasViewport): void;
  setScene(sceneId: string): void;
  setSignal(signal: AmbientSignal): void;
  setReducedMotion(reduced: boolean): void;
  /**
   * Writes a scene param (see AmbientSceneParam). Example: production feeds
   * `setParam("dayProgress", localClock01)` for sky scenes.
   */
  setParam(paramId: string, value: number): void;
  /** Loads a photo into the shared texture slot for photo scenes (CORS-safe URL). */
  setPhoto(url: string): void;
  /** Throttles rendering (15–60 fps; 60 = native rAF). */
  setFrameCap(fps: number): void;
  /** Stop rendering entirely while the document is hidden (default true). */
  setPauseWhenHidden(pause: boolean): void;
  /** Live render stats for monitoring overlays. frameMs is JS submit time, not GPU time. */
  getStats(): { fps: number; frameMs: number; dpr: number; resolution: string };
  resize(): void;
  start(): void;
  destroy(): void;
}
