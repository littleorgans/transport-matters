import { vi } from "vitest";

/**
 * Manual mock for `createAmbientBackground`, resolved by Vitest's `__mocks__`
 * convention when a test calls a bare `vi.mock(".../ambient/createAmbientBackground")`.
 *
 * jsdom implements no WebGL, so any test that mounts the real ambient backdrop
 * reaches `canvas.getContext("webgl")` and logs "Not implemented: HTMLCanvasElement's
 * getContext()". Tests that exercise route or surface behaviour rather than the WebGL
 * engine opt out by mocking this seam. The factory returns `null` — the same
 * context-less result the React layer already tolerates in production when no GL
 * context is available — so the backdrop still mounts its canvas element without
 * starting an engine.
 *
 * Override per test with `vi.mocked(createAmbientBackground).mockReturnValueOnce(fake)`.
 */
export const createAmbientBackground = vi.fn(() => null);
