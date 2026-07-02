import { act, screen } from "@testing-library/react";
import { queryClient } from "@tm/core";
import { installMockTransport, jsonResponse, restoreTransport } from "@tm/core/testing";
import { afterEach, describe, expect, it } from "vitest";
import { type MountedWindowChrome, mountWindowChrome } from "./mountWindowChrome";

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
  let chrome: MountedWindowChrome | null = null;

  afterEach(() => {
    act(() => {
      chrome?.unmount();
    });
    chrome = null;
    queryClient.clear();
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

    chrome = mountWindowChrome();

    expect(document.body.firstElementChild).toBe(chrome.host);
    expect(await screen.findByText("PREVIEW")).toHaveAccessibleName("Preview channel");
    expect(chrome.host.querySelector(".window-drag-region")).toHaveAttribute("aria-hidden", "true");
  });

  it("does not reuse cached meta between mounted chrome roots", async () => {
    window.transportMattersDesktop = { appName: "Transport Matters", platform: "darwin" };
    installMockTransport(() =>
      jsonResponse({
        ...previewMeta(),
        channel: "stable",
        channel_badge: null,
        channel_label: "Stable",
      }),
    );

    chrome = mountWindowChrome();

    await expect(screen.findByText("PREVIEW", {}, { timeout: 100 })).rejects.toThrow();
    expect(screen.queryByText("PREVIEW")).toBeNull();
  });
});
