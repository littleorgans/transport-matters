import { scenePrelude } from "../prelude.ts";
import type { AmbientSceneDefinition } from "../types.ts";

/**
 * Proof grid — the contract demonstrator, not the art. A fine survey lattice
 * locked exactly to the pane layer (depth 1.0: dots stay glued to panes
 * through pan/zoom — if they drift, the coordinate contract is broken), one
 * parallax mid-layer, and a state-colored breathing pool. Deliberately quiet;
 * real scenes replace this.
 */
export const proofGridScene: AmbientSceneDefinition = {
  id: "proof-grid",
  kind: "fragment",
  label: "Proof grid",
  description: "Quiet survey lattice locked to the world",
  fragmentShaderSource: `${scenePrelude}

float dotLattice(vec2 world, float spacing, float radius) {
  vec2 local = mod(world, spacing) - spacing * 0.5;
  return smoothstep(radius, radius * 0.4, length(local));
}

void main() {
  vec2 fragCoord = gl_FragCoord.xy;
  float time = uTime * (1.0 - clamp01(uReducedMotion));
  float intensity = clamp01(uIntensity);
  vec3 signal = signalColor();

  vec2 screen = (fragCoord - uResolution * 0.5) / uResolution.y;
  vec3 well = vec3(0.016, 0.016, 0.016);
  vec3 canvasTone = vec3(0.031, 0.031, 0.031);
  vec3 color = mix(well, canvasTone, clamp01(0.5 - screen.y * 0.4));

  // Pane-locked lattice (depth 1.0): the correctness proof.
  vec2 worldNear = worldPoint(fragCoord, 1.0);
  float near = dotLattice(worldNear, 96.0, 1.8);
  color += vec3(0.10, 0.10, 0.11) * near * 0.55;

  // Parallax mid-layer (depth 0.5): slides at half rate while panning.
  vec2 worldMid = worldPoint(fragCoord, 0.5);
  float mid = dotLattice(worldMid + 48.0, 192.0, 2.2);
  color += vec3(0.07, 0.07, 0.08) * mid * 0.45;

  // State pool: a soft breathing presence anchored in world space.
  vec2 poolWorld = worldUv(fragCoord, 0.7);
  float pool = fbm(poolWorld * 1.6 + time * 0.012);
  float breathe = 0.75 + 0.25 * sin(time * (0.25 + intensity * 0.6));
  color += signal * smoothstep(0.52, 0.95, pool) * breathe * (0.020 + intensity * 0.045);

  color = filmic(color);
  color *= screenVignette(fragCoord) * 0.25 + 0.75;
  color += (hash(fragCoord + fract(time) * 61.0) - 0.5) * 0.006;

  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`,
};
