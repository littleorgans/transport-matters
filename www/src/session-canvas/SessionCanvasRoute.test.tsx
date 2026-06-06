import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetCanvasStoreForTests } from "./model/canvasStore";
import { SessionCanvasRoute } from "./SessionCanvasRoute";
import {
  installMockTransport,
  jsonResponse,
  makeSessionEvent,
  makeSessionSummary,
  renderWithQuery,
  restoreTransport,
} from "./testUtils";

class MockEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn();
}

describe("SessionCanvasRoute", () => {
  afterEach(() => {
    restoreTransport();
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  it("renders the picker immediately", async () => {
    resetCanvasStoreForTests();
    window.history.pushState({}, "", "/canvas");
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(<SessionCanvasRoute />);

    expect(screen.getByRole("toolbar", { name: "Canvas commands" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("No sessions found for this canvas.")).toBeInTheDocument(),
    );
  });

  it("auto resolves the launched run into the transcript seam", async () => {
    resetCanvasStoreForTests();
    const session = makeSessionSummary({ session_id: "session-live", run_id: "run-live" });
    window.history.pushState(
      {},
      "",
      "/canvas?owner=local&workspace_hash=hash-1&cli=claude&run_id=run-live",
    );
    vi.stubGlobal("EventSource", MockEventSource);
    installMockTransport((path) =>
      path.includes("/events?")
        ? jsonResponse({
            events: [makeSessionEvent({ session_id: "session-live" })],
            next_from_seq: null,
          })
        : jsonResponse([session]),
    );

    renderWithQuery(<SessionCanvasRoute />);

    await waitFor(() => {
      expect(screen.getByText("hello transcript")).toBeInTheDocument();
    });
  });
});
