import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetApiTransport, setApiTransport } from "../../../api";
import type { PaneRecord, ViewerProps } from "../../model/paneRecords";
import { PROVENANCE_LABEL } from "../placeholder/provenance";
import { ResourcePane, type ResourcePaneRef } from "./ResourcePane";

const REF: ResourcePaneRef = {
  kind: "resource",
  owner: "local",
  sessionId: "s1",
  resourceId: "r1",
};

const base = {
  id: "r1",
  title: "fixture",
  mediaType: null as string | null,
  contentLength: null as number | null,
  contentProvenance: "captured",
  provenance: {},
};

function stubTransport(body: unknown): void {
  setApiTransport({
    request: () =>
      Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
  });
}

function paneProps(): ViewerProps<ResourcePaneRef> {
  const pane: PaneRecord & { contentRef: ResourcePaneRef } = {
    paneId: "resource:s1:r1",
    viewerId: "resource",
    title: "Resource r1",
    contentRef: REF,
    chromeState: "default",
    createdAt: "2026-06-08T00:00:00Z",
    lastFocusedAt: null,
  };
  return {
    pane,
    canvas: {
      id: "hash-1",
      owner: "local",
      workspaceHash: "hash-1",
      focusedPaneId: null,
      launch: { owner: "local", workspaceHash: "hash-1", cli: "claude", runId: null },
      launchStatus: "unavailable",
      launchSessionId: null,
    },
    actions: { closePane: vi.fn(), focusPane: vi.fn(), spawnOrFocusTranscript: vi.fn() },
  };
}

function renderPane(body: unknown): ReactElement {
  stubTransport(body);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ResourcePane {...paneProps()} />
    </QueryClientProvider>,
  ).container as unknown as ReactElement;
}

afterEach(() => {
  resetApiTransport();
});

describe("ResourcePane", () => {
  it("renders plain text through the text viewer with the captured provenance label", async () => {
    renderPane({
      ...base,
      kind: "text",
      mediaType: "text/plain",
      text: "line one\nline two",
      encoding: "utf-8",
      range: null,
      truncated: false,
    });
    expect(await screen.findByText("line one")).toBeInTheDocument();
    expect(screen.getByText("line two")).toBeInTheDocument();
    expect(screen.getByText(PROVENANCE_LABEL.captured)).toBeInTheDocument();
  });

  it("renders markdown text through the markdown viewer (rendered HTML elements, not raw)", async () => {
    renderPane({
      ...base,
      kind: "text",
      mediaType: "text/markdown",
      text: "## Heading\n\n**bold**",
      encoding: "utf-8",
      range: null,
      truncated: false,
    });
    expect(await screen.findByRole("heading", { name: "Heading" })).toBeInTheDocument();
    expect(screen.getByText("bold").tagName).toBe("STRONG");
  });

  it("labels native-record json with the native transcript provenance", async () => {
    renderPane({
      ...base,
      kind: "json",
      contentProvenance: "native-record",
      value: { a: 1 },
      text: null,
      truncated: false,
    });
    expect(await screen.findByText(PROVENANCE_LABEL["native-record"])).toBeInTheDocument();
  });

  it("renders a stable missing pane carrying the backend message, not a toast", async () => {
    renderPane({
      ...base,
      kind: "missing",
      reason: "uncorrelated",
      message: "Never correlated to a turn.",
      retryable: false,
    });
    expect(await screen.findByText("Never correlated to a turn.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(document.querySelector('[data-status="missing"]')).toBeInTheDocument();
  });

  it("renders a stable too-large pane for an oversized binary", async () => {
    renderPane({
      ...base,
      kind: "binary",
      contentLength: 9_000_000,
      downloadUrl: "/d",
      sha256: null,
      tooLarge: true,
    });
    expect(await screen.findByText(/9000000 bytes total/)).toBeInTheDocument();
    expect(document.querySelector('[data-status="too-large"]')).toBeInTheDocument();
  });

  it("renders the binary metadata viewer for an inline-able binary", async () => {
    renderPane({
      ...base,
      kind: "binary",
      mediaType: "application/zip",
      contentLength: 2048,
      downloadUrl: "/download",
      sha256: "abc",
      tooLarge: false,
    });
    expect(await screen.findByRole("link", { name: /open externally/i })).toHaveAttribute(
      "href",
      "/download",
    );
  });
});
