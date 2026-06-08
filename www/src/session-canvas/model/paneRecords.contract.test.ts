import { describe, expectTypeOf, it } from "vitest";
import type { CanvasPaneRef, PaneContentRef, PickerPaneRef } from "./paneRecords";

// The content contract is the four transcript kinds plus the local terminal
// surface (an interactive PTY, rendered through the same viewer registry). The
// session picker is canvas chrome and lives on CanvasPaneRef, not
// PaneContentRef. These assertions are enforced by `pnpm typecheck` (src test
// files are part of the tsc project).
describe("PaneContentRef contract", () => {
  it("exports the transcript content kinds plus the terminal surface", () => {
    expectTypeOf<PaneContentRef["kind"]>().toEqualTypeOf<
      "session-timeline" | "subagent-timeline" | "resource" | "provider-exchange" | "terminal"
    >();
  });

  it("keeps the session picker out of the content contract", () => {
    expectTypeOf<Extract<PaneContentRef, { kind: "session-picker" }>>().toEqualTypeOf<never>();
  });

  it("composes the picker into the canvas pane ref", () => {
    expectTypeOf<
      Extract<CanvasPaneRef, { kind: "session-picker" }>
    >().toEqualTypeOf<PickerPaneRef>();
  });
});
