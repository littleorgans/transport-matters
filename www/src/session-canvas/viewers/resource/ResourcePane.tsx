import type { ReactElement } from "react";
import type { ImageContentResponse, ResourceContentResponse } from "../../api/resourceContent";
import { useLocalFileContent } from "../../hooks/useLocalFileContent";
import { useResourceContent } from "../../hooks/useResourceContent";
import type { PaneContentRef, ViewerProps } from "../../model/paneRecords";
import { ResourcePaneStateView } from "../placeholder/paneState";
import { BinaryResourceViewer } from "./BinaryResourceViewer";
import { ImageResourceViewer } from "./ImageResourceViewer";
import { JsonResourceViewer } from "./JsonResourceViewer";
import { MarkdownResourceViewer } from "./MarkdownResourceViewer";
import { ProviderExchangeResourceViewer } from "./ProviderExchangeResourceViewer";
import { type ResourceView, resolveResourceContent } from "./resourceState";
import { TextResourceViewer } from "./TextResourceViewer";

export type ResourcePaneRef = Extract<PaneContentRef, { kind: "resource" }>;
type DbResourcePaneRef = Extract<ResourcePaneRef, { sessionId: string; resourceId: string }>;

/**
 * Resource pane orchestrator. Fetches the resource content endpoint, then maps
 * the typed response onto either a stable pane state (loading / missing /
 * too-large / ...) or a real viewer. The provenance label always comes from the
 * fetched content so the pane never claims a truth it is not showing. Stable
 * pane states render the backend message and keep their affordances; they never
 * collapse into a generic toast.
 */
export function ResourcePane({ pane }: ViewerProps<ResourcePaneRef>): ReactElement {
  const ref = pane.contentRef;
  if ("source" in ref && ref.source === "path") return <LocalFileResourcePane path={ref.path} />;
  if ("source" in ref && ref.source === "url") return <UrlImageResourcePane url={ref.url} />;
  return <DbResourcePane contentRef={ref} />;
}

function DbResourcePane({ contentRef }: { contentRef: DbResourcePaneRef }): ReactElement {
  const query = useResourceContent({
    sessionId: contentRef.sessionId,
    resourceId: contentRef.resourceId,
    owner: contentRef.owner,
  });
  return (
    <ResourceQueryPane
      data={query.data}
      error={query.error}
      isPending={query.isPending}
      loadingProvenance="captured"
    />
  );
}

function LocalFileResourcePane({ path }: { path: string }): ReactElement {
  const query = useLocalFileContent(path);
  return (
    <ResourceQueryPane
      data={query.data}
      error={query.error}
      isPending={query.isPending}
      loadingProvenance="current"
    />
  );
}

function UrlImageResourcePane({ url }: { url: string }): ReactElement {
  const content: ImageContentResponse = {
    kind: "image",
    id: url,
    title: url.split("/").filter(Boolean).at(-1) ?? url,
    mediaType: null,
    contentLength: null,
    contentProvenance: "current",
    provenance: { source: "url", url },
    url,
    bytesBase64: null,
    width: null,
    height: null,
    alt: null,
  };
  return <ImageResourceViewer content={content} />;
}

function ResourceQueryPane({
  data,
  error,
  isPending,
  loadingProvenance,
}: {
  data: ResourceContentResponse | undefined;
  error: Error | null;
  isPending: boolean;
  loadingProvenance: ResourceContentResponse["contentProvenance"];
}): ReactElement {
  if (isPending) {
    return <ResourcePaneStateView provenance={loadingProvenance} state={{ status: "loading" }} />;
  }

  if (error || data === undefined) {
    const message = error instanceof Error ? error.message : undefined;
    return (
      <ResourcePaneStateView
        messageOverride={message}
        provenance={loadingProvenance}
        state={{ status: "missing" }}
      />
    );
  }

  return <ResolvedResourceContent content={data} />;
}

function ResolvedResourceContent({ content }: { content: ResourceContentResponse }): ReactElement {
  const resolution = resolveResourceContent(content);
  if (resolution.kind === "state") {
    return (
      <ResourcePaneStateView
        messageOverride={resolution.message}
        provenance={content.contentProvenance}
        state={resolution.state}
      />
    );
  }

  return (
    <ResourcePaneStateView provenance={content.contentProvenance} state={{ status: "ready" }}>
      <ResourceBody view={resolution.view} />
    </ResourcePaneStateView>
  );
}

function ResourceBody({ view }: { view: ResourceView }): ReactElement {
  switch (view.viewer) {
    case "markdown":
      return <MarkdownResourceViewer content={view.content} />;
    case "text":
      return <TextResourceViewer content={view.content} />;
    case "json":
      return <JsonResourceViewer content={view.content} />;
    case "image":
      return <ImageResourceViewer content={view.content} />;
    case "binary":
      return <BinaryResourceViewer content={view.content} />;
    case "exchange":
      return (
        <ProviderExchangeResourceViewer
          exchangeId={view.content.exchangeId}
          initialView={view.content.initialView}
        />
      );
  }
}
