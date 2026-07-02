import { scenePrelude } from "../prelude.ts";
import type { AmbientFragmentSceneDefinition } from "../types.ts";

/**
 * Reference sea — raymarched ocean with a full day cycle (dawn → midday →
 * dusk → night → storm), driven by uDayProgress. Ported from the v1 lab
 * (branch feat/world-modes-photo-study) onto the ambient scene contract.
 *
 * Screen-space by design: a horizon scene reads as the room the canvas sits
 * in, so it deliberately ignores pan/zoom.
 *
 * The sun is a brightness dial (uSun, 0..1), not a position: the sun keeps
 * its normal arc and only its strength scales. sun=0 gates every direct sun
 * term to zero (no disc, glare, or glow — a calm, sky-lit sea); sun=1 is full
 * midday glare. With no lift the night sun stays below the horizon, so there
 * is no phantom sun and the lower half stays alive across the whole dial.
 */
export const referenceSeaScene: AmbientFragmentSceneDefinition = {
  id: "reference-sea",
  kind: "fragment",
  label: "Reference sea",
  description: "Raymarched ocean, full day cycle, with a sun-glare control",
  params: [
    {
      id: "dayProgress",
      uniform: "uDayProgress",
      label: "day",
      min: 0,
      max: 1,
      step: 0.001,
      defaultValue: 0.25,
    },
    {
      id: "sun",
      uniform: "uSun",
      label: "sun",
      min: 0,
      max: 1,
      step: 0.01,
      defaultValue: 0,
    },
  ],
  fragmentShaderSource: `${scenePrelude}

uniform float uSun;

#define MARCH_STEPS 22
#define REFINE_STEPS 5

float smoother(float x) {
  x = clamp01(x);
  return x * x * x * (x * (x * 6.0 - 15.0) + 10.0);
}

float dayScene() {
  return min(floor(clamp01(uDayProgress) * 4.0), 3.0);
}

float dayBlend() {
  return clamp01(uDayProgress) * 4.0 - dayScene();
}

vec3 sCol(vec3 c0, vec3 c1, vec3 c2, vec3 c3, vec3 c4) {
  int si = int(dayScene());
  vec3 a = c0;
  vec3 b = c1;
  if (si == 1) { a = c1; b = c2; }
  else if (si == 2) { a = c2; b = c3; }
  else if (si == 3) { a = c3; b = c4; }
  return mix(a, b, dayBlend());
}

float sF(float c0, float c1, float c2, float c3, float c4) {
  int si = int(dayScene());
  float a = c0;
  float b = c1;
  if (si == 1) { a = c1; b = c2; }
  else if (si == 2) { a = c2; b = c3; }
  else if (si == 3) { a = c3; b = c4; }
  return mix(a, b, dayBlend());
}

mat2 rot(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}

float waveH(vec2 p, float t, float amp, float storm) {
  float h = 0.0;

  vec2 swell1 = normalize(vec2(1.0, 0.28));
  vec2 swell2 = normalize(vec2(-0.48, 0.88));
  vec2 swell3 = normalize(vec2(0.82, -0.16));

  swell2 = rot(storm * 0.18) * swell2;
  swell3 = rot(-storm * 0.14) * swell3;

  float d1 = dot(p, swell1);
  float d2 = dot(p, swell2);
  float d3 = dot(p, swell3);

  h += amp * 0.66 * sin(d1 * 0.42 + t * 0.38);
  h += amp * 0.22 * sin(d1 * 0.94 - t * 0.62);
  h += amp * 0.14 * sin(d2 * 1.18 - t * 0.82);
  h += amp * 0.09 * sin(d3 * 1.82 + t * 1.04);

  h += amp * (0.11 + storm * 0.07) * sin(p.x * 1.45 - t * 0.76 + p.y * 0.66);
  h += amp * (0.07 + storm * 0.05) * sin(p.x * 2.85 + t * 1.06 - p.y * 0.52);
  h += amp * (0.04 + storm * 0.03) * sin(p.x * 4.60 - t * 1.50 + p.y * 1.02);

  float micro = noise(p * 14.0 + vec2(t * 0.18, t * 0.06)) - 0.5;
  h += micro * amp * (0.010 + storm * 0.008);

  return h;
}

vec3 waveNorm(vec2 p, float t, float amp, float storm) {
  float e = 0.018;
  float hL = waveH(p - vec2(e, 0.0), t, amp, storm);
  float hR = waveH(p + vec2(e, 0.0), t, amp, storm);
  float hD = waveH(p - vec2(0.0, e), t, amp, storm);
  float hU = waveH(p + vec2(0.0, e), t, amp, storm);
  return normalize(vec3(-(hR - hL) / (2.0 * e), 1.0, -(hU - hD) / (2.0 * e)));
}

float starField(vec2 uv) {
  vec2 gv = floor(uv);
  vec2 lv = fract(uv) - 0.5;

  float h = hash(gv);
  float size = mix(0.012, 0.0025, h);
  float d = length(lv + vec2(hash(gv + 3.1) - 0.5, hash(gv + 7.3) - 0.5) * 0.25);
  float star = smoothstep(size, 0.0, d);
  star *= smoothstep(0.82, 1.0, h);
  return star;
}

void main() {
  vec2 uv = (gl_FragCoord.xy - uResolution * 0.5) / uResolution.y;

  float s = smoother(clamp01(uDayProgress));
  float t = uTime * (1.0 - clamp01(uReducedMotion));

  float camY = mix(1.14, 1.03, s);
  camY += sin(s * PI * 1.4) * 0.028;
  float camZ = mix(0.08, -0.18, s);
  float pitch = mix(0.115, 0.088, s);

  vec3 ro = vec3(0.0, camY, camZ);
  vec3 rd = normalize(vec3(uv.x, uv.y - pitch, -1.4));

  float storm = smoothstep(0.80, 1.0, s);
  float night = smoothstep(0.56, 0.84, s);

  vec3 skyTop = sCol(
    vec3(0.18, 0.06, 0.24),
    vec3(0.05, 0.24, 0.68),
    vec3(0.26, 0.06, 0.04),
    vec3(0.01, 0.01, 0.05),
    vec3(0.04, 0.05, 0.09)
  );

  vec3 skyHori = sCol(
    vec3(0.92, 0.48, 0.18),
    vec3(0.42, 0.62, 0.90),
    vec3(0.88, 0.32, 0.04),
    vec3(0.03, 0.05, 0.14),
    vec3(0.15, 0.17, 0.23)
  );

  vec3 sunCol = sCol(
    vec3(1.0, 0.62, 0.22),
    vec3(1.0, 0.96, 0.80),
    vec3(1.0, 0.38, 0.05),
    vec3(0.70, 0.75, 0.94),
    vec3(0.26, 0.28, 0.34)
  );

  vec3 seaDeep = sCol(
    vec3(0.08, 0.05, 0.12),
    vec3(0.03, 0.14, 0.34),
    vec3(0.10, 0.06, 0.04),
    vec3(0.00, 0.01, 0.03),
    vec3(0.03, 0.04, 0.07)
  );

  vec3 seaShlo = sCol(
    vec3(0.28, 0.17, 0.24),
    vec3(0.09, 0.38, 0.60),
    vec3(0.24, 0.13, 0.06),
    vec3(0.04, 0.06, 0.16),
    vec3(0.07, 0.10, 0.14)
  );

  vec3 fogCol = sCol(
    vec3(0.80, 0.50, 0.30),
    vec3(0.58, 0.72, 0.90),
    vec3(0.70, 0.28, 0.05),
    vec3(0.02, 0.03, 0.08),
    vec3(0.12, 0.14, 0.18)
  );

  /* sun (0..1) is a brightness dial, not a position: 0 = no sun at all (calm,
     sky-lit sea), 1 = full midday glare. The sun keeps its arc and only its
     strength scales, so every part of the dial reads, and with no lift the
     night sun stays below the horizon (no phantom). At 0 every sun term gates
     to zero — no disc, no glare, no glow. */
  float sunDim = clamp01(uSun);

  /* The sun rides a full closed circle: above the horizon over s in [0, 0.58]
     (the old arc), then onward beneath it back to the dawn point, so position
     and glow stay continuous across the wrap. */
  float sunAngle = s < 0.58 ? s * (PI / 0.58) : PI + (s - 0.58) * (PI / 0.42);
  float sunArcX = cos(sunAngle) * -0.75;
  float sunArcY = sin(sunAngle) * 0.38 - 0.08;

  vec3 sunDir = normalize(vec3(sunArcX, sunArcY, -1.0));
  vec3 moonDir = normalize(vec3(-0.14, 0.42, -1.0));

  float waveAmp = sF(0.082, 0.070, 0.100, 0.054, 0.30);
  waveAmp += storm * 0.020;

  float fogDen = sF(0.020, 0.010, 0.022, 0.034, 0.046);
  float moonAmt = sF(0.0, 0.0, 0.05, 0.92, 0.06);

  // Sun visibility gates on its own (unlifted) height: below the horizon at
  // night → no contribution, so no phantom. sunDim then scales the strength.
  float sunAbove = step(0.0, sunDir.y) * sunDim;
  float sunGlow = smoothstep(-0.10, 0.06, sunDir.y) * sunDim;

  vec3 col;

  if (rd.y < 0.0) {
    float tFlat = ro.y / (-rd.y);
    float stepSize = tFlat / float(MARCH_STEPS);
    float tMarch = stepSize;

    for (int i = 0; i < MARCH_STEPS; i++) {
      vec2 wpTest = ro.xz + rd.xz * tMarch;
      float wy = ro.y + rd.y * tMarch;
      if (wy < waveH(wpTest, t, waveAmp, storm)) break;
      tMarch += stepSize;
    }

    float ta = tMarch - stepSize;
    float tb = tMarch;

    for (int i = 0; i < REFINE_STEPS; i++) {
      float tm = (ta + tb) * 0.5;
      vec2 wpm = ro.xz + rd.xz * tm;
      if (ro.y + rd.y * tm < waveH(wpm, t, waveAmp, storm)) tb = tm;
      else ta = tm;
    }

    tMarch = (ta + tb) * 0.5;

    vec2 wp = ro.xz + rd.xz * tMarch;
    vec3 n = waveNorm(wp, t, waveAmp, storm);
    vec3 vDir = -rd;

    float fres = pow(1.0 - clamp(dot(n, vDir), 0.0, 1.0), 4.0);

    vec3 refl = reflect(rd, n);
    float rh = clamp(refl.y, 0.0, 1.0);

    vec3 reflSky = mix(skyHori, skyTop, pow(rh, 0.42));
    reflSky = mix(reflSky, skyHori, 0.12);

    float rSun = max(dot(refl, sunDir), 0.0);
    reflSky += sunCol * pow(rSun, 120.0) * 2.0 * sunGlow;
    reflSky += sunCol * pow(rSun, 18.0) * 0.07 * sunGlow;

    if (moonAmt > 0.04) {
      float rMoon = max(dot(refl, moonDir), 0.0);
      reflSky += vec3(0.72, 0.80, 0.95) * pow(rMoon, 120.0) * 0.78 * moonAmt;
    }

    float depth = exp(-tMarch * 0.40);
    vec3 waterC = mix(seaDeep, seaShlo, depth * 0.5);

    vec3 absorb = vec3(0.85, 0.92, 1.0);
    waterC *= mix(vec3(1.0), absorb, clamp(tMarch * 0.25, 0.0, 1.0));

    col = mix(waterC, reflSky, 0.15 + fres * 0.34);

    float spec = pow(max(dot(reflect(-sunDir, n), vDir), 0.0), 200.0);
    col += sunCol * spec * 1.10 * sunAbove;

    float broadSpec = pow(max(dot(reflect(-sunDir, n), vDir), 0.0), 32.0);
    col += sunCol * broadSpec * 0.12 * sunGlow;

    float sunLine = pow(max(dot(reflect(rd, n), sunDir), 0.0), 8.0);
    col += sunCol * sunLine * 0.48 * smoothstep(0.0, 0.35, -rd.y) * sunGlow;

    float sparkle = noise(wp * 18.0 + vec2(t * 0.55, t * 0.22));
    sparkle = smoothstep(0.94, 1.0, sparkle);
    col += sunCol * sparkle * 0.08 * sunGlow * sunAbove;

    if (moonAmt > 0.04) {
      float mSpec = pow(max(dot(reflect(-moonDir, n), vDir), 0.0), 520.0);
      col += vec3(0.72, 0.80, 0.95) * mSpec * 0.09 * moonAmt;
    }

    float hC = waveH(wp, t, waveAmp, storm);
    float hL = waveH(wp - vec2(0.025, 0.0), t, waveAmp, storm);
    float hR = waveH(wp + vec2(0.025, 0.0), t, waveAmp, storm);
    float hD = waveH(wp - vec2(0.0, 0.025), t, waveAmp, storm);
    float hU = waveH(wp + vec2(0.0, 0.025), t, waveAmp, storm);

    float curvature = hR + hL + hU + hD - 4.0 * hC;
    float foam = clamp(curvature * (24.0 + storm * 10.0), 0.0, 1.0);
    col += foam * vec3(1.0) * (0.03 + storm * 0.10);

    float fog = 1.0 - exp(-tMarch * fogDen * 1.65);
    col = mix(col, fogCol, fog);
  } else {
    float h = clamp(rd.y, 0.0, 1.0);
    col = mix(skyHori, skyTop, pow(h, 0.38));
  }

  float horizonW = 0.008;
  float skyMix = smoothstep(-horizonW, horizonW, rd.y);

  vec3 skyCol;
  {
    float h = clamp(rd.y, 0.0, 1.0);
    skyCol = mix(skyHori, skyTop, pow(h, 0.38));

    float cloudBand = noise(rd.x * 5.5 + rd.y * 3.0 + vec2(t * 0.015, 0.0));
    float cloudBand2 = noise(rd.x * 8.0 - rd.y * 4.0 - vec2(t * 0.010, 0.0));
    float clouds = smoothstep(0.62, 0.86, cloudBand * 0.65 + cloudBand2 * 0.35);
    clouds *= smoothstep(-0.02, 0.24, rd.y);
    clouds *= 0.08 + storm * 0.18;

    vec3 cloudCol = mix(
      vec3(1.0, 0.82, 0.65),
      vec3(0.42, 0.48, 0.56),
      storm
    );

    skyCol = mix(skyCol, mix(skyCol * 0.97, cloudCol, 0.35), clouds);

    float sd = max(dot(rd, sunDir), 0.0);
    skyCol += sunCol * pow(sd, 380.0) * 6.8 * sunGlow;
    skyCol += sunCol * pow(sd, 22.0)  * 0.20 * sunGlow;
    skyCol += sunCol * pow(sd, 5.0)   * 0.09 * sunGlow;

    float sunDisk = smoothstep(0.99925, 0.99995, dot(rd, sunDir));
    skyCol += sunCol * sunDisk * 2.6 * sunGlow;

    float horizonBand = exp(-abs(rd.y) * 24.0);
    skyCol += sunCol * horizonBand * 0.11 * sunGlow;

    float viewSun = max(dot(rd, sunDir), 0.0);
    skyCol += sunCol * pow(viewSun, 3.0) * 0.035 * sunGlow;

    if (moonAmt > 0.04) {
      float md = max(dot(rd, moonDir), 0.0);
      skyCol += vec3(0.88, 0.92, 1.0) * pow(md, 820.0) * 7.4 * moonAmt;
      skyCol += vec3(0.88, 0.92, 1.0) * pow(md, 6.0)   * 0.045 * moonAmt;
    }

    if (night > 0.02) {
      vec2 starUv = rd.xy / max(0.12, rd.z + 1.6);
      starUv *= 140.0;
      float stars = starField(starUv) + starField(starUv * 0.55 + 11.7) * 0.65;
      stars *= smoothstep(0.02, 0.26, rd.y);
      stars *= (1.0 - storm * 0.85);
      skyCol += vec3(0.80, 0.88, 1.0) * stars * night * 0.82;
    }

    float horizonMist = exp(-abs(rd.y) * mix(38.0, 22.0, storm));
    skyCol += fogCol * horizonMist * (0.09 + storm * 0.10);

    skyCol = mix(skyCol, skyCol * vec3(0.91, 0.94, 0.98), storm * 0.22);
  }

  col = mix(col, skyCol, skyMix);

  float hEdge = smoothstep(-0.008, 0.018, rd.y);
  col = mix(fogCol, col, hEdge * 0.25 + 0.75);

  float grain = hash(gl_FragCoord.xy * 0.5 + floor(t * 12.0)) - 0.5;
  col += grain * 0.006;

  gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
`,
};
