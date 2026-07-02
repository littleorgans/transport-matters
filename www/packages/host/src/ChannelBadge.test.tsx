import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "@/session-canvas/testUtils";
import { ChannelBadge } from "./ChannelBadge";

function metaPayload(channel: "stable" | "preview") {
  return {
    channel,
    channel_badge:
      channel === "preview" ? { text: "PREVIEW", color: "amber", hex: "#f59e0b" } : null,
    channel_label: channel === "preview" ? "Preview" : "Stable",
    cwd: "/tmp/project",
    harnesses: [],
    run_id: null,
    workspace_id: "project/hash",
  };
}

describe("ChannelBadge", () => {
  afterEach(() => {
    restoreTransport();
  });

  it("returns null for stable", async () => {
    const handler = vi.fn(() => jsonResponse(metaPayload("stable")));
    installMockTransport(handler);

    renderWithQuery(<ChannelBadge />);

    await waitFor(() => expect(handler).toHaveBeenCalledWith("/api/meta"));
    expect(screen.queryByText("PREVIEW")).toBeNull();
  });

  it("renders the amber preview pill", async () => {
    installMockTransport(() => jsonResponse(metaPayload("preview")));

    renderWithQuery(<ChannelBadge />);

    const badge = await screen.findByText("PREVIEW");
    expect(badge).toHaveStyle({ backgroundColor: "#f59e0b" });
    expect(badge).toHaveAccessibleName("Preview channel");
  });
});
