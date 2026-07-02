import { isRecord } from "../lib/isRecord";

/**
 * Legacy sceneId remap for scene collapses that keep the same schema version.
 * `reference-sea-ii` folded into `reference-sea` + the `sun` param (0 = calm),
 * which is the scene's default, so the remap is a pure id rewrite.
 */
const LEGACY_SCENE_IDS: Record<string, string> = {
  "reference-sea-ii": "reference-sea",
};

/**
 * Rewrites a stored/imported theme record's legacy sceneId. Anything that is
 * not a record with a remappable sceneId is returned by identity, so callers
 * can rely on `===` to detect a no-op. Run before validation at every
 * persistence seam: validateThemeDefinition (covers preset load + JSON import)
 * and the persisted theme store's rehydration migrate. Without it, a stored
 * theme on the removed scene id fails validation and is dropped — silent loss.
 */
export const normalizeLegacyTheme = (value: unknown): unknown => {
  if (!isRecord(value) || !isRecord(value.settings)) return value;
  const sceneId = value.settings.sceneId;
  if (typeof sceneId !== "string") return value;
  const next = LEGACY_SCENE_IDS[sceneId];
  if (!next) return value;
  return { ...value, settings: { ...value.settings, sceneId: next } };
};
