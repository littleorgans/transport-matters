import { scenePrelude } from "../prelude.ts";
import type { AmbientSceneDefinition } from "../types.ts";

/**
 * Photo study — an ingested photograph graded into the canvas. uPhotoGrade
 * sweeps from subtle dim (0: photographic, darkened for pane legibility) to
 * full duotone (1: luminance remapped onto the state palette — amber at a
 * breakpoint, rose on error). Sits at low parallax (depth 0.18) with soft
 * edges fading into the route-shell dark; state glow breathes through the
 * highlights at any grade.
 */
export const photoStudyScene: AmbientSceneDefinition = {
  id: "photo-study",
  kind: "fragment",
  label: "Photo study",
  description: "Your photography, graded into the canvas",
  usesPhoto: true,
  params: [
    {
      id: "photoGrade",
      uniform: "uPhotoGrade",
      label: "grade",
      min: 0,
      max: 1,
      step: 0.01,
      defaultValue: 0.55,
    },
  ],
  fragmentShaderSource: `${scenePrelude}

uniform sampler2D uPhotoTex;
uniform float uPhotoAspect;
uniform float uPhotoReady;
uniform float uPhotoGrade;

void main() {
  vec2 fragCoord = gl_FragCoord.xy;
  float time = uTime * (1.0 - clamp01(uReducedMotion));
  float intensity = clamp01(uIntensity);
  vec3 signal = signalColor();

  vec2 viewportCss = uResolution / uDpr;
  vec2 world = worldPoint(fragCoord, 0.18);
  vec2 centered = world - viewportCss * 0.5;

  float aspect = max(uPhotoAspect, 0.0001);
  float photoHeight = max(viewportCss.y, viewportCss.x / aspect) * 1.18;
  vec2 tex = centered / vec2(photoHeight * aspect, photoHeight) + 0.5;

  vec3 color = vec3(0.014, 0.014, 0.015);

  vec2 inside = step(vec2(0.0), tex) * step(tex, vec2(1.0));
  vec2 edge = smoothstep(0.0, 0.06, tex) * smoothstep(1.0, 0.94, tex);
  float fade = inside.x * inside.y * edge.x * edge.y * clamp01(uPhotoReady);

  vec3 photo = texture2D(uPhotoTex, tex).rgb;
  float luma = dot(photo, vec3(0.2126, 0.7152, 0.0722));

  vec3 dimmed = photo * photo * (0.30 + intensity * 0.14);
  vec3 duotone = mix(vec3(0.012, 0.012, 0.013), signal, pow(luma, 1.5)) * (0.40 + intensity * 0.25);
  vec3 graded = mix(dimmed, duotone, clamp01(uPhotoGrade));

  color = mix(color, graded, fade);

  float breathe = 0.5 + 0.5 * sin(time * (0.25 + intensity * 0.8));
  color += signal * pow(luma, 3.0) * fade * breathe * intensity * 0.05;

  float mist = fbm(world * 0.002 + time * 0.01);
  color += vec3(0.012, 0.012, 0.014) * smoothstep(0.4, 0.9, mist) * (1.0 - clamp01(uPhotoReady));

  color *= screenVignette(fragCoord) * 0.5 + 0.5;

  float grain = hash(fragCoord + fract(time) * 59.0) - 0.5;
  color += grain * 0.010;

  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`,
};
