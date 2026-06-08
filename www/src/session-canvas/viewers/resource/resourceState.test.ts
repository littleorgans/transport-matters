import { describe, expect, it } from "vitest";
import type {
  BinaryContentResponse,
  ExchangeRedirectResponse,
  ImageContentResponse,
  JsonContentResponse,
  MissingResourceReason,
  MissingResourceResponse,
  ResourceContentBase,
  TextContentResponse,
} from "../../api/resourceContent";
import { isMarkdown, missingState, resolveResourceContent } from "./resourceState";

const base: ResourceContentBase = {
  id: "r1",
  title: "Resource",
  mediaType: null,
  contentLength: null,
  contentProvenance: "captured",
  provenance: {},
};

function text(overrides: Partial<TextContentResponse> = {}): TextContentResponse {
  return {
    ...base,
    kind: "text",
    text: "hello",
    encoding: "utf-8",
    range: null,
    truncated: false,
    ...overrides,
  };
}

function json(overrides: Partial<JsonContentResponse> = {}): JsonContentResponse {
  return { ...base, kind: "json", value: { a: 1 }, text: null, truncated: false, ...overrides };
}

function image(overrides: Partial<ImageContentResponse> = {}): ImageContentResponse {
  return {
    ...base,
    kind: "image",
    url: "/x.png",
    bytesBase64: null,
    width: null,
    height: null,
    alt: null,
    ...overrides,
  };
}

function binary(overrides: Partial<BinaryContentResponse> = {}): BinaryContentResponse {
  return {
    ...base,
    kind: "binary",
    downloadUrl: "/d",
    sha256: null,
    tooLarge: false,
    ...overrides,
  };
}

function exchange(overrides: Partial<ExchangeRedirectResponse> = {}): ExchangeRedirectResponse {
  return {
    ...base,
    kind: "exchange-redirect",
    exchangeId: "e1",
    route: "/inspect/e1",
    initialView: null,
    ...overrides,
  };
}

function missing(reason: MissingResourceReason, over: Partial<MissingResourceResponse> = {}) {
  return {
    ...base,
    kind: "missing" as const,
    reason,
    message: `msg-${reason}`,
    retryable: false,
    ...over,
  };
}

describe("isMarkdown", () => {
  it("recognizes markdown media types regardless of params or casing", () => {
    expect(isMarkdown("text/markdown")).toBe(true);
    expect(isMarkdown("text/markdown; charset=utf-8")).toBe(true);
    expect(isMarkdown("TEXT/MARKDOWN")).toBe(true);
    expect(isMarkdown("text/x-markdown")).toBe(true);
    expect(isMarkdown("application/x.foo+markdown")).toBe(true);
  });

  it("rejects non-markdown and null", () => {
    expect(isMarkdown("text/plain")).toBe(false);
    expect(isMarkdown("application/json")).toBe(false);
    expect(isMarkdown(null)).toBe(false);
    expect(isMarkdown("")).toBe(false);
  });
});

describe("resolveResourceContent", () => {
  it("routes plain text to the text viewer", () => {
    expect(resolveResourceContent(text({ mediaType: "text/plain" }))).toEqual({
      kind: "ready",
      view: { viewer: "text", content: text({ mediaType: "text/plain" }) },
    });
  });

  it("routes markdown text to the markdown viewer", () => {
    const r = resolveResourceContent(text({ mediaType: "text/markdown" }));
    expect(r).toMatchObject({ kind: "ready", view: { viewer: "markdown" } });
  });

  it("routes json to the json viewer", () => {
    expect(resolveResourceContent(json())).toMatchObject({
      kind: "ready",
      view: { viewer: "json" },
    });
  });

  it("routes native-record json to the json viewer (label differentiates, not selection)", () => {
    const r = resolveResourceContent(json({ contentProvenance: "native-record" }));
    expect(r).toMatchObject({ kind: "ready", view: { viewer: "json" } });
  });

  it("routes image to the image viewer", () => {
    expect(resolveResourceContent(image())).toMatchObject({
      kind: "ready",
      view: { viewer: "image" },
    });
  });

  it("routes a normal binary to the binary viewer", () => {
    expect(resolveResourceContent(binary())).toMatchObject({
      kind: "ready",
      view: { viewer: "binary" },
    });
  });

  it("renders a too-large state (with byte size, no synthetic message) for an oversized binary", () => {
    const r = resolveResourceContent(binary({ tooLarge: true, contentLength: 4096 }));
    expect(r).toEqual({
      kind: "state",
      state: { status: "too-large", byteSize: 4096 },
    });
  });

  it("routes exchange-redirect to the exchange viewer", () => {
    expect(resolveResourceContent(exchange())).toMatchObject({
      kind: "ready",
      view: { viewer: "exchange" },
    });
  });

  it("maps every missing reason to a stable state and passes the backend message", () => {
    const cases: Array<[MissingResourceReason, ResourcePaneStatusName]> = [
      ["not-found", "missing"],
      ["uncorrelated", "missing"],
      ["outside-workspace", "outside-workspace"],
      ["permission-denied", "permission-denied"],
      ["too-large", "too-large"],
      ["debug-unavailable", "debug-unavailable"],
      ["unsupported", "binary-unsupported"],
    ];
    for (const [reason, status] of cases) {
      const r = resolveResourceContent(missing(reason));
      expect(r.kind).toBe("state");
      if (r.kind !== "state") throw new Error("unreachable");
      expect(r.state.status).toBe(status);
      expect(r.message).toBe(`msg-${reason}`);
    }
  });

  it("carries byte size on a too-large missing reason and media type on unsupported", () => {
    expect(missingState(missing("too-large", { contentLength: 99 }))).toEqual({
      status: "too-large",
      byteSize: 99,
    });
    expect(missingState(missing("unsupported", { mediaType: "application/pdf" }))).toEqual({
      status: "binary-unsupported",
      mediaType: "application/pdf",
    });
  });
});

type ResourcePaneStatusName =
  | "missing"
  | "too-large"
  | "binary-unsupported"
  | "outside-workspace"
  | "permission-denied"
  | "debug-unavailable";
