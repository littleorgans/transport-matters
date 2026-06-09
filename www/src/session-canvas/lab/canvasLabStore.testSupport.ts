// Shared lab-store test helper. Lives in a non-test module so both canvasLabStore.test.ts (captured
// runs) and canvasLabStore.persistence.test.ts (reload converge) use one definition, not two copies.

/** The pane ids whose content ref is a captured run, in insertion order. */
export function capturedPaneIds(contentRefs: Record<string, { kind: string }>): string[] {
  return Object.entries(contentRefs)
    .filter(([, ref]) => ref.kind === "captured-run")
    .map(([id]) => id);
}
