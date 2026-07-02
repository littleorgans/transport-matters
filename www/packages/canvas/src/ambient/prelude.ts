/**
 * Shared GLSL prelude for ambient scenes.
 *
 * Coordinate contract (matches production exactly):
 * - uPan / uScale are the CanvasViewport in CSS px (panX, panY, scale).
 * - worldPoint(fragCoord, depth) returns *production world coordinates*
 *   (CSS px at scale 1, y-down — the same space pane WorldRects live in).
 *   depth 1.0 → locked to the pane layer; depth 0.0 → screen-fixed.
 * - worldUv is worldPoint / 1000 for comfortable shader-scale numbers.
 *
 * Signal contract:
 * - uStateFrom/uStateTo/uStateBlend animate between AMBIENT_STATE_INDEX
 *   values (the module blends internally; scenes just call signalColor()).
 * - uIntensity 0..1; uReducedMotion freezes uTime upstream (still passed for
 *   scenes that want to swap animation for static variation).
 */
export const scenePrelude = `
precision highp float;

uniform vec2 uResolution;
uniform float uDpr;
uniform float uTime;
uniform vec2 uPan;
uniform float uScale;
uniform float uStateFrom;
uniform float uStateTo;
uniform float uStateBlend;
uniform float uIntensity;
uniform float uReducedMotion;
uniform float uDayProgress;

#define PI 3.141592653589793

float clamp01(float value) {
  return clamp(value, 0.0, 1.0);
}

float hash(vec2 point) {
  return fract(sin(dot(point, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 point) {
  vec2 cell = floor(point);
  vec2 local = fract(point);
  local = local * local * (3.0 - 2.0 * local);

  float bottomLeft = hash(cell);
  float bottomRight = hash(cell + vec2(1.0, 0.0));
  float topLeft = hash(cell + vec2(0.0, 1.0));
  float topRight = hash(cell + vec2(1.0, 1.0));

  return mix(
    mix(bottomLeft, bottomRight, local.x),
    mix(topLeft, topRight, local.x),
    local.y
  );
}

float fbm(vec2 point) {
  float value = 0.0;
  float amplitude = 0.5;

  for (int i = 0; i < 4; i++) {
    value += amplitude * noise(point);
    point = point * 2.03 + vec2(19.7, 7.3);
    amplitude *= 0.5;
  }

  return value;
}

/* idle ivory · working sage · waiting amber · error rose */
vec3 stateColor(float stateIndex) {
  vec3 color = vec3(0.91, 0.89, 0.86);
  color = mix(color, vec3(0.49, 0.79, 0.63), step(0.5, stateIndex));
  color = mix(color, vec3(0.83, 0.69, 0.49), step(1.5, stateIndex));
  color = mix(color, vec3(0.83, 0.53, 0.61), step(2.5, stateIndex));
  return color;
}

vec3 signalColor() {
  return mix(stateColor(uStateFrom), stateColor(uStateTo), clamp01(uStateBlend));
}

vec2 worldPoint(vec2 fragCoord, float depth) {
  vec2 css = vec2(fragCoord.x, uResolution.y - fragCoord.y) / uDpr;
  float depthScale = mix(1.0, uScale, depth);
  vec2 depthPan = uPan * depth;
  return (css - depthPan) / depthScale;
}

vec2 worldUv(vec2 fragCoord, float depth) {
  return worldPoint(fragCoord, depth) / 1000.0;
}

float screenVignette(vec2 fragCoord) {
  vec2 centered = (fragCoord - uResolution * 0.5) / uResolution.y;
  return smoothstep(1.15, 0.25, length(centered * vec2(0.78, 1.0)));
}

vec3 filmic(vec3 x) {
  x = max(vec3(0.0), x);
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}
`;
