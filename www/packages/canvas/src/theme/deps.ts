/**
 * The single wiring point between the ported theme contract and the ported
 * ambient scene/photo data. Everything that validates a theme shares these
 * deps so scene and photo knowledge lives in one place.
 */
import { photoCatalog } from "../ambient/photos";
import { sceneRegistry } from "../ambient/sceneRegistry";
import { createPhotoLookup } from "./types";
import type { ThemeValidationDeps } from "./validate";

export const themeValidationDeps: ThemeValidationDeps = {
  sceneRegistry,
  photoLookup: createPhotoLookup(photoCatalog),
};
