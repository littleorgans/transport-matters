import { describe, expectTypeOf, it } from "vitest";
import type { CanvasPaneRef, PaneContentRef, PickerPaneRef } from "./paneRecords";

// The exported transcript content contract must stay exactly the four spec kinds
// (NOTES/transcript-canvas-ui-frontend.md:50-54). The session picker is canvas
// chrome and lives on CanvasPaneRef, not PaneContentRef. These assertions are
// enforced by `pnpm typecheck` (src test files are part of the tsc project).
describe("PaneContentRef contract", () => {
  it("exports exactly the four transcript content kinds", () => {
    expectTypeOf<PaneContentRef["kind"]>().toEqualTypeOf<
      "session-timeline" | "subagent-timeline" | "resource" | "provider-exchange"
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
