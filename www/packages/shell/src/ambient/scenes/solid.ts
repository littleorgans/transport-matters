import { scenePrelude } from "../prelude.ts";
import type { AmbientSceneDefinition } from "../types.ts";

/**
 * Solid — no scene. The production route-shell gradient as a shader: a
 * near-black canvas with the accent breathing in at the top-left corner at
 * very low amplitude. The "background off" option that still belongs to the
 * theme system.
 */
export const solidScene: AmbientSceneDefinition = {
  id: "solid",
  kind: "fragment",
  label: "Solid",
  description: "No scene — the bare canvas, state-aware",
  fragmentShaderSource: `${scenePrelude}

void main() {
  vec2 fragCoord = gl_FragCoord.xy;
  float time = uTime * (1.0 - clamp01(uReducedMotion));
  float intensity = clamp01(uIntensity);
  vec3 signal = signalColor();

  vec2 screen = fragCoord / uResolution;

  vec3 well = vec3(0.016, 0.016, 0.016);
  vec3 canvasTone = vec3(0.031, 0.031, 0.031);
  vec3 color = mix(well, canvasTone, clamp01(screen.x * 0.7 + (1.0 - screen.y) * 0.5));

  float corner = exp(-length(vec2(screen.x, 1.0 - screen.y) - vec2(0.2, 0.18)) * 2.4);
  float breathe = 0.8 + 0.2 * sin(time * (0.2 + intensity * 0.4));
  color += signal * corner * breathe * (0.020 + intensity * 0.025);

  color += (hash(fragCoord + fract(time) * 37.0) - 0.5) * 0.006;

  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`,
};
