import { photoStudyScene } from "./scenes/photo-study.ts";
import { proofGridScene } from "./scenes/proof-grid.ts";
import { referenceSeaScene } from "./scenes/reference-sea.ts";
import { solidScene } from "./scenes/solid.ts";
import type { AmbientFragmentSceneDefinition, AmbientSceneDefinition } from "./types.ts";

export interface AmbientSceneParamMetadata {
  id: string;
  label: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  legacyUniform?: string;
}

export interface AmbientSceneSwatchStop {
  color: string;
  at: number;
}

export interface AmbientSceneSwatch {
  kind: "gradient" | "color";
  label: string;
  stops: readonly AmbientSceneSwatchStop[];
}

export interface AmbientSceneMetadata {
  id: string;
  label: string;
  kind: AmbientSceneDefinition["kind"];
  usesPhoto: boolean;
  params: readonly AmbientSceneParamMetadata[];
  swatch: AmbientSceneSwatch;
}

export interface AmbientSceneRegistry {
  all(): readonly AmbientSceneDefinition[];
  metadata(): readonly AmbientSceneMetadata[];
  metadataFor(sceneId: string): AmbientSceneMetadata | undefined;
  fragmentScenes(): readonly AmbientFragmentSceneDefinition[];
  get(sceneId: string): AmbientSceneDefinition | undefined;
  getFragment(sceneId: string): AmbientFragmentSceneDefinition | undefined;
  has(sceneId: string): boolean;
  paramsFor(sceneId: string): readonly AmbientSceneParamMetadata[];
  paramFor(sceneId: string, paramId: string): AmbientSceneParamMetadata | undefined;
  paramIdForUniform(sceneId: string, uniform: string): string | undefined;
  fragmentUniformFor(sceneId: string, paramId: string): string | undefined;
}

const registeredScenes = [referenceSeaScene, photoStudyScene, proofGridScene, solidScene] as const;

const sceneSwatches: Record<string, AmbientSceneSwatch> = {
  "reference-sea": {
    kind: "gradient",
    label: "Sea glare",
    stops: [
      { color: "rgb(6 28 44)", at: 0 },
      { color: "rgb(40 112 143)", at: 0.58 },
      { color: "rgb(237 202 138)", at: 1 },
    ],
  },
  "photo-study": {
    kind: "gradient",
    label: "Charcoal photo wash",
    stops: [
      { color: "rgb(4 4 5)", at: 0 },
      { color: "rgb(34 28 25)", at: 0.55 },
      { color: "rgb(118 90 56)", at: 1 },
    ],
  },
  "proof-grid": {
    kind: "gradient",
    label: "Graphite lattice",
    stops: [
      { color: "rgb(4 4 4)", at: 0 },
      { color: "rgb(16 16 18)", at: 0.76 },
      { color: "rgb(39 41 45)", at: 1 },
    ],
  },
  solid: {
    kind: "gradient",
    label: "Raised canvas",
    stops: [
      { color: "rgb(4 4 4)", at: 0 },
      { color: "rgb(8 8 8)", at: 1 },
    ],
  },
};

const isFragmentScene = (scene: AmbientSceneDefinition): scene is AmbientFragmentSceneDefinition =>
  scene.kind === "fragment";

const assertRegistryIntegrity = (scenes: readonly AmbientSceneDefinition[]) => {
  const sceneIds = new Set<string>();
  for (const scene of scenes) {
    if (sceneIds.has(scene.id)) throw new Error(`Duplicate ambient scene id: ${scene.id}`);
    sceneIds.add(scene.id);

    const paramIds = new Set<string>();
    for (const param of scene.params ?? []) {
      if (paramIds.has(param.id))
        throw new Error(`Duplicate ambient scene param id: ${scene.id}.${param.id}`);
      paramIds.add(param.id);
    }
  }
};

const buildMetadata = (scene: AmbientSceneDefinition): AmbientSceneMetadata => {
  const swatch = sceneSwatches[scene.id];
  if (!swatch) throw new Error(`Ambient scene ${scene.id} is missing registry swatch metadata.`);

  return {
    id: scene.id,
    label: scene.label,
    kind: scene.kind,
    usesPhoto: scene.usesPhoto ?? false,
    params: (scene.params ?? []).map((param) => ({
      id: param.id,
      label: param.label,
      min: param.min,
      max: param.max,
      step: param.step,
      defaultValue: param.defaultValue,
      ...(param.uniform ? { legacyUniform: param.uniform } : {}),
    })),
    swatch,
  };
};

const createAmbientSceneRegistry = (
  scenes: readonly AmbientSceneDefinition[],
): AmbientSceneRegistry => {
  assertRegistryIntegrity(scenes);

  const sceneById = new Map(scenes.map((scene) => [scene.id, scene]));
  const fragmentScenes = scenes.filter(isFragmentScene);
  const metadata = scenes.map(buildMetadata);
  const metadataById = new Map(metadata.map((entry) => [entry.id, entry]));

  return {
    all: () => scenes,
    metadata: () => metadata,
    metadataFor: (sceneId) => metadataById.get(sceneId),
    fragmentScenes: () => fragmentScenes,
    get: (sceneId) => sceneById.get(sceneId),
    getFragment: (sceneId) => {
      const scene = sceneById.get(sceneId);
      return scene?.kind === "fragment" ? scene : undefined;
    },
    has: (sceneId) => sceneById.has(sceneId),
    paramsFor: (sceneId) => metadataById.get(sceneId)?.params ?? [],
    paramFor: (sceneId, paramId) =>
      metadataById.get(sceneId)?.params.find((param) => param.id === paramId),
    paramIdForUniform: (sceneId, uniform) =>
      metadataById.get(sceneId)?.params.find((param) => param.legacyUniform === uniform)?.id,
    fragmentUniformFor: (sceneId, paramId) => {
      const scene = sceneById.get(sceneId);
      return scene?.kind === "fragment"
        ? scene.params?.find((param) => param.id === paramId)?.uniform
        : undefined;
    },
  };
};

export const sceneRegistry = createAmbientSceneRegistry(registeredScenes);
