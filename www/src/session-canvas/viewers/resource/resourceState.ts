import type {
  BinaryContentResponse,
  ExchangeRedirectResponse,
  ImageContentResponse,
  JsonContentResponse,
  MissingResourceResponse,
  ResourceContentResponse,
  TextContentResponse,
} from "../../api/resourceContent";
import type { ResourcePaneState } from "../placeholder/paneState";

/**
 * Which real viewer a successful resource response resolves to. The backend
 * union carries six `kind`s; the eight UX viewers in the frontend spec collapse
 * onto these because `tool-output` has no backend discriminator (it is `text`
 * or `json` with copy controls) and `native-record` is `json` with a
 * `native-record` provenance label. Markdown is `text` refined by media type.
 */
export type ResourceView =
  | { viewer: "markdown"; content: TextContentResponse }
  | { viewer: "text"; content: TextContentResponse }
  | { viewer: "json"; content: JsonContentResponse }
  | { viewer: "image"; content: ImageContentResponse }
  | { viewer: "binary"; content: BinaryContentResponse }
  | { viewer: "exchange"; content: ExchangeRedirectResponse };

/**
 * The outcome of a resource fetch: either a ready view, or a stable pane state
 * (missing / too-large / unsupported / ...). An optional `message` rides the
 * state so the pane can render the backend's own text for reasons that have no
 * dedicated state (e.g. `uncorrelated`), never a generic toast. When absent
 * (e.g. an oversized binary), the state's canned detail renders the byte size.
 */
export type ResourceResolution =
  | { kind: "ready"; view: ResourceView }
  | { kind: "state"; state: ResourcePaneState; message?: string };

const MARKDOWN_MEDIA_TYPES = new Set([
  "text/markdown",
  "text/x-markdown",
  "application/markdown",
  "application/x-markdown",
]);

/** True when a text resource's media type marks it as markdown. */
export function isMarkdown(mediaType: string | null): boolean {
  if (!mediaType) return false;
  const normalized = mediaType.split(";", 1)[0]?.trim().toLowerCase() ?? "";
  return MARKDOWN_MEDIA_TYPES.has(normalized) || normalized.endsWith("+markdown");
}

/** Pure mapping from a resource content response to a view or a pane state. */
export function resolveResourceContent(content: ResourceContentResponse): ResourceResolution {
  switch (content.kind) {
    case "text":
      return {
        kind: "ready",
        view: { viewer: isMarkdown(content.mediaType) ? "markdown" : "text", content },
      };
    case "json":
      return { kind: "ready", view: { viewer: "json", content } };
    case "image":
      return { kind: "ready", view: { viewer: "image", content } };
    case "binary":
      if (content.tooLarge) {
        // No backend message on the binary path; the canned detail renders the
        // byte size, which is more useful than a generic line.
        return { kind: "state", state: tooLargeState(content.contentLength) };
      }
      return { kind: "ready", view: { viewer: "binary", content } };
    case "exchange-redirect":
      return { kind: "ready", view: { viewer: "exchange", content } };
    case "missing":
      return { kind: "state", state: missingState(content), message: content.message };
  }
}

function tooLargeState(byteSize: number | null): ResourcePaneState {
  return byteSize !== null ? { status: "too-large", byteSize } : { status: "too-large" };
}

/** Map a typed missing reason to one of the eight stable pane states. */
export function missingState(content: MissingResourceResponse): ResourcePaneState {
  switch (content.reason) {
    case "too-large":
      return tooLargeState(content.contentLength);
    case "unsupported":
      return content.mediaType
        ? { status: "binary-unsupported", mediaType: content.mediaType }
        : { status: "binary-unsupported" };
    case "outside-workspace":
      return { status: "outside-workspace" };
    case "permission-denied":
      return { status: "permission-denied" };
    case "debug-unavailable":
      return { status: "debug-unavailable" };
    case "not-found":
    case "uncorrelated":
      return { status: "missing" };
  }
}
