import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { installMockTransport, jsonResponse, restoreTransport } from "../session-canvas/testUtils";
import { mountWindowChrome } from "./mountWindowChrome";

function previewMeta() {
  return {
    channel: "preview",
    channel_badge: { text: "PREVIEW", color: "amber", hex: "#f59e0b" },
    channel_label: "Preview",
    cwd: "/tmp/project",
    harnesses: [],
    run_id: null,
    workspace_id: "project/hash",
  };
}

describe("mountWindowChrome", () => {
  afterEach(() => {
    restoreTransport();
    document.body.innerHTML = "";
    delete window.transportMattersDesktop;
  });

  it("prepends desktop chrome and renders the channel badge in the host root", async () => {
    window.transportMattersDesktop = { appName: "Transport Matters", platform: "darwin" };
    installMockTransport(() => jsonResponse(previewMeta()));
    const root = document.createElement("div");
    root.id = "root";
    document.body.append(root);

    const host = mountWindowChrome();

    expect(document.body.firstElementChild).toBe(host);
    expect(await screen.findByText("PREVIEW")).toHaveAccessibleName("Preview channel");
    expect(host.querySelector(".window-drag-region")).toHaveAttribute("aria-hidden", "true");
  });
});
