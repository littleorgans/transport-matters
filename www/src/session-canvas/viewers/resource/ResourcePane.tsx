import type { ReactElement } from "react";
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
  const query = useResourceContent({
    sessionId: ref.sessionId,
    resourceId: ref.resourceId,
    owner: ref.owner,
  });

  if (query.isPending) {
    return <ResourcePaneStateView provenance="captured" state={{ status: "loading" }} />;
  }

  if (query.error || query.data === undefined) {
    const message = query.error instanceof Error ? query.error.message : undefined;
    return (
      <ResourcePaneStateView
        messageOverride={message}
        provenance="captured"
        state={{ status: "missing" }}
      />
    );
  }

  const content = query.data;
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
