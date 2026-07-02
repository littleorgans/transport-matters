import type { CanvasViewport } from "./engine/viewport.ts";
import {
  AMBIENT_STATE_INDEX,
  type AmbientBackground,
  type AmbientFragmentSceneDefinition,
  type AmbientSceneDefinition,
  type AmbientSignal,
} from "./types.ts";

const vertexShaderSource = `
attribute vec2 aPosition;

void main() {
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const STATE_BLEND_MS = 900;
const MAX_DPR = 1.5;

interface ProgramHandle {
  program: WebGLProgram;
  vertexShader: WebGLShader;
  fragmentShader: WebGLShader;
  position: number;
  uniforms: Map<string, WebGLUniformLocation>;
  paramUniforms: ReadonlyMap<string, string>;
}

const UNIFORM_NAMES = [
  "uResolution",
  "uDpr",
  "uTime",
  "uPan",
  "uScale",
  "uStateFrom",
  "uStateTo",
  "uStateBlend",
  "uIntensity",
  "uReducedMotion",
  "uPhotoTex",
  "uPhotoAspect",
  "uPhotoReady",
];

const isFragmentScene = (scene: AmbientSceneDefinition): scene is AmbientFragmentSceneDefinition =>
  scene.kind === "fragment";

const getWebGlContext = (canvas: HTMLCanvasElement): WebGLRenderingContext | null =>
  canvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    depth: false,
    stencil: false,
    preserveDrawingBuffer: false,
    powerPreference: "high-performance",
  });

const createQuadBuffer = (gl: WebGLRenderingContext): WebGLBuffer => {
  const buffer = gl.createBuffer();
  if (!buffer) throw new Error("Unable to create WebGL buffer.");
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  return buffer;
};

const compileShader = (gl: WebGLRenderingContext, type: number, source: string): WebGLShader => {
  const shader = gl.createShader(type);
  if (!shader) throw new Error("Unable to create shader.");
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) ?? "Unknown shader compile error.";
    gl.deleteShader(shader);
    throw new Error(message);
  }
  return shader;
};

const createProgram = (
  gl: WebGLRenderingContext,
  fragmentSource: string,
  paramUniforms: ReadonlyMap<string, string>,
): ProgramHandle => {
  const vertexShader = compileShader(gl, gl.VERTEX_SHADER, vertexShaderSource);
  const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  if (!program) throw new Error("Unable to create WebGL program.");

  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(program) ?? "Unknown WebGL link error.";
    gl.deleteProgram(program);
    gl.deleteShader(vertexShader);
    gl.deleteShader(fragmentShader);
    throw new Error(message);
  }

  const uniforms = new Map<string, WebGLUniformLocation>();
  for (const name of [...UNIFORM_NAMES, ...paramUniforms.values()]) {
    const location = gl.getUniformLocation(program, name);
    if (location) uniforms.set(name, location);
  }

  return {
    fragmentShader,
    paramUniforms,
    position: gl.getAttribLocation(program, "aPosition"),
    program,
    uniforms,
    vertexShader,
  };
};

const createParamUniforms = (
  scene: AmbientFragmentSceneDefinition,
): ReadonlyMap<string, string> => {
  const uniforms = new Map<string, string>();
  for (const param of scene.params ?? []) {
    if (param.uniform) uniforms.set(param.id, param.uniform);
  }
  return uniforms;
};

const createPrograms = (
  gl: WebGLRenderingContext,
  scenes: readonly AmbientFragmentSceneDefinition[],
): Map<string, ProgramHandle> => {
  const programs = new Map<string, ProgramHandle>();
  for (const scene of scenes) {
    programs.set(
      scene.id,
      createProgram(gl, scene.fragmentShaderSource, createParamUniforms(scene)),
    );
  }
  return programs;
};

const createInitialParamValues = (
  scenes: readonly AmbientFragmentSceneDefinition[],
): Map<string, number> => {
  const values = new Map<string, number>();
  for (const scene of scenes) {
    for (const param of scene.params ?? []) {
      if (!values.has(param.id)) values.set(param.id, param.defaultValue);
    }
  }
  return values;
};

const createDefaultPhotoTexture = (gl: WebGLRenderingContext): WebGLTexture => {
  const photoTexture = gl.createTexture();
  if (!photoTexture) throw new Error("Unable to create WebGL photo texture.");
  gl.bindTexture(gl.TEXTURE_2D, photoTexture);
  gl.texImage2D(
    gl.TEXTURE_2D,
    0,
    gl.RGB,
    1,
    1,
    0,
    gl.RGB,
    gl.UNSIGNED_BYTE,
    new Uint8Array([4, 4, 4]),
  );
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  return photoTexture;
};

const warnUnsupportedModuleScenes = (scenes: readonly AmbientSceneDefinition[]) => {
  for (const scene of scenes) {
    if (scene.kind === "module") {
      console.warn(
        `Ambient module scene ${scene.id} is typed but unsupported by the fragment renderer.`,
      );
    }
  }
};

class FragmentAmbientBackground implements AmbientBackground {
  private viewport: CanvasViewport = { panX: 0, panY: 0, scale: 1 };
  private signal: AmbientSignal = { state: "idle", intensity: 0.3 };
  private stateFromIndex = AMBIENT_STATE_INDEX[this.signal.state];
  private stateChangedAt = 0;
  private reducedMotion = false;
  private frameCap = 60;
  private pauseWhenHidden = true;
  private frameMsEma = 0;
  private fpsEma = 0;
  private lastRendered = 0;
  private frameHandle = 0;
  private running = false;
  private sceneTime = 0;
  private lastTick = 0;
  private dpr = 1;
  private photoReady = 0;
  private photoAspect = 16 / 9;
  private photoLoadToken = 0;
  private activeSceneId: string;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly gl: WebGLRenderingContext,
    private readonly buffer: WebGLBuffer,
    private readonly programs: ReadonlyMap<string, ProgramHandle>,
    private readonly paramValues: Map<string, number>,
    private readonly photoTexture: WebGLTexture,
    fragmentScenes: readonly AmbientFragmentSceneDefinition[],
    initialSceneId?: string,
  ) {
    const fallbackScene = fragmentScenes[0];
    if (!fallbackScene) {
      throw new Error("FragmentAmbientBackground requires at least one fragment scene.");
    }
    this.activeSceneId =
      initialSceneId && programs.has(initialSceneId) ? initialSceneId : fallbackScene.id;
    this.resize();
  }

  setViewport(viewport: CanvasViewport) {
    this.viewport = viewport;
  }

  setScene(sceneId: string) {
    if (this.programs.has(sceneId)) this.activeSceneId = sceneId;
  }

  setSignal(signal: AmbientSignal) {
    if (signal.state !== this.signal.state) {
      this.stateFromIndex = AMBIENT_STATE_INDEX[this.signal.state];
      this.stateChangedAt = performance.now();
    }
    this.signal = signal;
  }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
  }

  setParam(paramId: string, value: number) {
    this.paramValues.set(paramId, value);
  }

  setFrameCap(fps: number) {
    this.frameCap = Math.min(60, Math.max(15, fps));
  }

  setPauseWhenHidden(pause: boolean) {
    this.pauseWhenHidden = pause;
  }

  getStats() {
    return {
      fps: Math.round(this.fpsEma),
      frameMs: Math.round(this.frameMsEma * 100) / 100,
      dpr: this.dpr,
      resolution: `${this.canvas.width}×${this.canvas.height}`,
    };
  }

  setPhoto(url: string) {
    const token = ++this.photoLoadToken;
    this.photoReady = 0;

    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      if (token !== this.photoLoadToken) return;
      try {
        this.gl.bindTexture(this.gl.TEXTURE_2D, this.photoTexture);
        this.gl.texImage2D(
          this.gl.TEXTURE_2D,
          0,
          this.gl.RGB,
          this.gl.RGB,
          this.gl.UNSIGNED_BYTE,
          image,
        );
        this.photoAspect = image.width / Math.max(1, image.height);
        this.photoReady = 1;
      } catch (error) {
        console.warn("Ambient photo texture upload failed (CORS?)", error);
      }
    };
    image.onerror = () => {
      if (token === this.photoLoadToken) console.warn(`Ambient photo failed to load: ${url}`);
    };
    image.src = url;
  }

  resize() {
    const cssWidth = Math.max(1, Math.round(this.canvas.clientWidth || window.innerWidth));
    const cssHeight = Math.max(1, Math.round(this.canvas.clientHeight || window.innerHeight));
    this.dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    const width = Math.round(cssWidth * this.dpr);
    const height = Math.round(cssHeight * this.dpr);

    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
      this.gl.viewport(0, 0, width, height);
    }
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.lastTick = 0;
    this.frameHandle = requestAnimationFrame(this.renderFrame);
  }

  destroy() {
    this.running = false;
    cancelAnimationFrame(this.frameHandle);
    for (const handle of this.programs.values()) {
      this.gl.deleteProgram(handle.program);
      this.gl.deleteShader(handle.vertexShader);
      this.gl.deleteShader(handle.fragmentShader);
    }
    this.gl.deleteBuffer(this.buffer);
    this.gl.deleteTexture(this.photoTexture);
  }

  private setFloat(handle: ProgramHandle, name: string, value: number) {
    const location = handle.uniforms.get(name);
    if (location) this.gl.uniform1f(location, value);
  }

  private renderFrame = (now: number) => {
    if (!this.running) return;
    this.frameHandle = requestAnimationFrame(this.renderFrame);

    if (this.pauseWhenHidden && document.visibilityState === "hidden") {
      this.lastTick = 0;
      return;
    }

    if (this.frameCap < 60 && now - this.lastRendered < 1000 / this.frameCap - 1) return;

    const renderStarted = performance.now();
    const delta = this.lastTick === 0 ? 0 : (now - this.lastTick) / 1000;
    this.lastTick = now;
    if (!this.reducedMotion) this.sceneTime += Math.min(delta, 0.1);

    this.updateFrameStats(now);

    const handle = this.programs.get(this.activeSceneId);
    if (!handle) return;

    const blendRaw = Math.min(1, Math.max(0, (now - this.stateChangedAt) / STATE_BLEND_MS));
    const blend = blendRaw * blendRaw * (3 - 2 * blendRaw);

    // biome-ignore lint/correctness/useHookAtTopLevel: WebGL useProgram, not a React hook
    this.gl.useProgram(handle.program);
    this.gl.bindBuffer(this.gl.ARRAY_BUFFER, this.buffer);
    this.gl.enableVertexAttribArray(handle.position);
    this.gl.vertexAttribPointer(handle.position, 2, this.gl.FLOAT, false, 0, 0);

    this.setVectorUniforms(handle);
    this.setFloat(handle, "uDpr", this.dpr);
    this.setFloat(handle, "uTime", this.sceneTime);
    this.setFloat(handle, "uScale", this.viewport.scale);
    this.setFloat(handle, "uStateFrom", this.stateFromIndex);
    this.setFloat(handle, "uStateTo", AMBIENT_STATE_INDEX[this.signal.state]);
    this.setFloat(handle, "uStateBlend", blend);
    this.setFloat(handle, "uIntensity", this.signal.intensity);
    this.setFloat(handle, "uReducedMotion", this.reducedMotion ? 1 : 0);
    this.setSceneParamUniforms(handle);
    this.setPhotoUniforms(handle);

    this.gl.drawArrays(this.gl.TRIANGLE_STRIP, 0, 4);

    const renderMs = performance.now() - renderStarted;
    this.frameMsEma = this.frameMsEma === 0 ? renderMs : this.frameMsEma * 0.9 + renderMs * 0.1;
  };

  private updateFrameStats(now: number) {
    if (this.lastRendered > 0) {
      const interval = now - this.lastRendered;
      if (interval > 0)
        this.fpsEma =
          this.fpsEma === 0 ? 1000 / interval : this.fpsEma * 0.9 + (1000 / interval) * 0.1;
    }
    this.lastRendered = now;
  }

  private setVectorUniforms(handle: ProgramHandle) {
    const resolution = handle.uniforms.get("uResolution");
    if (resolution) this.gl.uniform2f(resolution, this.canvas.width, this.canvas.height);
    const pan = handle.uniforms.get("uPan");
    if (pan) this.gl.uniform2f(pan, this.viewport.panX, this.viewport.panY);
  }

  private setSceneParamUniforms(handle: ProgramHandle) {
    for (const [paramId, uniform] of handle.paramUniforms) {
      const value = this.paramValues.get(paramId);
      if (value !== undefined) this.setFloat(handle, uniform, value);
    }
  }

  private setPhotoUniforms(handle: ProgramHandle) {
    const photoTexLocation = handle.uniforms.get("uPhotoTex");
    if (!photoTexLocation) return;

    this.gl.activeTexture(this.gl.TEXTURE0);
    this.gl.bindTexture(this.gl.TEXTURE_2D, this.photoTexture);
    this.gl.uniform1i(photoTexLocation, 0);
    this.setFloat(handle, "uPhotoAspect", this.photoAspect);
    this.setFloat(handle, "uPhotoReady", this.photoReady);
  }
}

/**
 * Framework-agnostic ambient background renderer. Owns its rAF loop, DPR
 * sizing, scene programs, and signal-state blending. The host only forwards
 * viewport, signal, scene, and param changes.
 */
export function createAmbientBackground(
  canvas: HTMLCanvasElement,
  scenes: readonly AmbientSceneDefinition[],
  initialSceneId?: string,
): AmbientBackground | null {
  warnUnsupportedModuleScenes(scenes);
  const fragmentScenes = scenes.filter(isFragmentScene);
  const gl = getWebGlContext(canvas);
  if (!gl || fragmentScenes.length === 0) return null;

  gl.disable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);
  gl.disable(gl.BLEND);

  return new FragmentAmbientBackground(
    canvas,
    gl,
    createQuadBuffer(gl),
    createPrograms(gl, fragmentScenes),
    createInitialParamValues(fragmentScenes),
    createDefaultPhotoTexture(gl),
    fragmentScenes,
    initialSceneId,
  );
}
