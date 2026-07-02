import { useEffect, useRef } from "react";
import { createAmbientBackground } from "../../ambient/createAmbientBackground";
import { sceneRegistry } from "../../ambient/sceneRegistry";
import type { AmbientBackground } from "../../ambient/types";
import { useThemeStore } from "../../stores/themeStore";
import {
  DAY_PROGRESS_PARAM_ID,
  LIVE_DAY_INTERVAL_MS,
  sceneDayProgress,
} from "../../theme/dayCycle";
import { themeValidationDeps } from "../../theme/deps";
import type { ThemeSettings } from "../../theme/types";

export function sceneHasDayProgress(sceneId: string): boolean {
  return sceneRegistry.paramsFor(sceneId).some((param) => param.id === DAY_PROGRESS_PARAM_ID);
}

/**
 * Pushes one theme's scene into a running ambient renderer. setParam keys by
 * the scene param id ("dayProgress"), never the GLSL uniform ("uDayProgress");
 * the renderer maps id to uniform internally, and a uniform name here would be
 * a silent no-op. Params the theme does not override fall back to the scene
 * defaults so a stale value from the previous scene never leaks through.
 */
export function driveAmbientScene(bg: AmbientBackground, settings: ThemeSettings): void {
  bg.setScene(settings.sceneId);
  driveSceneParams(bg, settings);
  if (sceneRegistry.metadataFor(settings.sceneId)?.usesPhoto) {
    const photo = themeValidationDeps.photoLookup.getPhoto(settings.photoKey);
    if (photo) bg.setPhoto(photo.imageUrl);
  }
}

/**
 * The live tuning path: applies only param values, which the render loop reads
 * every frame. Scrubbing a slider goes through here so the sky moves on the
 * next frame without re-sending the scene or re-fetching the photo.
 */
export function driveSceneParams(bg: AmbientBackground, settings: ThemeSettings): void {
  for (const param of sceneRegistry.paramsFor(settings.sceneId)) {
    bg.setParam(param.id, settings.sceneParams[param.id] ?? param.defaultValue);
  }
}

/**
 * The themed scene layer behind the canvas viewport. Renders nothing while
 * unthemed, and the engine returns null without WebGL, so the route shell's
 * CSS gradient remains the fallback background in both cases.
 */
export function AmbientBackdrop() {
  const settings = useThemeStore((state) => state.theme?.settings ?? null);
  if (!settings) return null;
  return <AmbientCanvas settings={settings} />;
}

function AmbientCanvas({ settings }: { settings: ThemeSettings }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const bgRef = useRef<AmbientBackground | null>(null);
  const initialSceneId = useRef(settings.sceneId);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    // Headless automation (Playwright/Selenium set navigator.webdriver) runs on
    // a software GL backend, where the per-frame raymarch pegs the GPU process
    // and the canvas-lab stops responding — every pointer-driven e2e then times
    // out. No behavioral or visual test depends on the backdrop, so skip the
    // WebGL engine under automation and let the route shell's CSS gradient show,
    // the same fallback as a browser without WebGL.
    if (navigator.webdriver) return;
    const bg = createAmbientBackground(canvas, sceneRegistry.all(), initialSceneId.current);
    if (!bg) return;
    bgRef.current = bg;
    bg.start();

    const onResize = () => bg.resize();
    window.addEventListener("resize", onResize);
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    bg.setReducedMotion(motion.matches);
    const onMotionChange = (event: MediaQueryListEvent) => bg.setReducedMotion(event.matches);
    motion.addEventListener("change", onMotionChange);

    return () => {
      window.removeEventListener("resize", onResize);
      motion.removeEventListener("change", onMotionChange);
      bg.destroy();
      bgRef.current = null;
    };
  }, []);

  const drivenSettings = useRef<ThemeSettings | null>(null);
  useEffect(() => {
    const bg = bgRef.current;
    if (!bg) return;
    const previous = drivenSettings.current;
    drivenSettings.current = settings;
    if (
      !previous ||
      previous.sceneId !== settings.sceneId ||
      previous.photoKey !== settings.photoKey
    ) {
      driveAmbientScene(bg, settings);
    } else if (previous.sceneParams !== settings.sceneParams) {
      driveSceneParams(bg, settings);
    }
  }, [settings]);

  // The live day clock. Declared after the drive effect so each clock push
  // lands on top of whatever baseline the drive just re-applied. Pushes go
  // straight to the renderer, never into the store: the stored baseline must
  // not absorb a time of day. Leaving live mode restores the baseline params.
  const liveDayCycle = useThemeStore((state) => state.liveDayCycle);
  useEffect(() => {
    const bg = bgRef.current;
    if (!bg || !sceneHasDayProgress(settings.sceneId)) return;
    if (!liveDayCycle) {
      driveSceneParams(bg, settings);
      return;
    }
    // sceneDayProgress, not localDayProgress: the renderer wants the scene's
    // sun-curve domain; the slider keeps showing wall-clock time.
    const push = () => bg.setParam(DAY_PROGRESS_PARAM_ID, sceneDayProgress(new Date()));
    push();
    const timer = window.setInterval(push, LIVE_DAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [liveDayCycle, settings]);

  return <canvas aria-hidden className="canvas-ambient-backdrop" ref={canvasRef} />;
}
