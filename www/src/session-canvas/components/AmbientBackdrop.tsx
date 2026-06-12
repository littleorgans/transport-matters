import { useEffect, useRef } from "react";
import { createAmbientBackground } from "../../ambient/createAmbientBackground";
import { sceneRegistry } from "../../ambient/sceneRegistry";
import type { AmbientBackground } from "../../ambient/types";
import { useThemeStore } from "../../stores/themeStore";
import { themeValidationDeps } from "../../theme/deps";
import type { ThemeSettings } from "../../theme/types";

/**
 * Pushes one theme's scene into a running ambient renderer. setParam keys by
 * the scene param id ("dayProgress"), never the GLSL uniform ("uDayProgress");
 * the renderer maps id to uniform internally, and a uniform name here would be
 * a silent no-op. Params the theme does not override fall back to the scene
 * defaults so a stale value from the previous scene never leaks through.
 */
export function driveAmbientScene(bg: AmbientBackground, settings: ThemeSettings): void {
  bg.setScene(settings.sceneId);
  for (const param of sceneRegistry.paramsFor(settings.sceneId)) {
    bg.setParam(param.id, settings.sceneParams[param.id] ?? param.defaultValue);
  }
  if (sceneRegistry.metadataFor(settings.sceneId)?.usesPhoto) {
    const photo = themeValidationDeps.photoLookup.getPhoto(settings.photoKey);
    if (photo) bg.setPhoto(photo.imageUrl);
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

  useEffect(() => {
    const bg = bgRef.current;
    if (bg) driveAmbientScene(bg, settings);
  }, [settings]);

  return <canvas aria-hidden className="canvas-ambient-backdrop" ref={canvasRef} />;
}
