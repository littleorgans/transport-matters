import type { ReactElement } from "react";
import { type DetailTab, ExchangeDetail } from "../../../components/ExchangeDetail";
import "./exchange-viewer.css";

/**
 * Provider-exchange viewer. Reuses the existing ExchangeDetail component and its
 * query code rather than reimplementing wire rendering. The no-op onMissing
 * keeps the canvas decoupled from legacy route state (acceptance 7): a missing
 * exchange renders ExchangeDetail's own error body instead of mutating the
 * legacy selection store.
 */
export function ProviderExchangeResourceViewer({
  exchangeId,
  initialView,
}: {
  exchangeId: string;
  initialView?: string | null;
}): ReactElement {
  return (
    <div className="canvas-exchange">
      <ExchangeDetail id={exchangeId} initialTab={toDetailTab(initialView)} onMissing={noop} />
    </div>
  );
}

function noop(): void {}

/** Map the backend's initialView onto an ExchangeDetail tab. */
function toDetailTab(view: string | null | undefined): DetailTab {
  switch (view) {
    case "request":
      return "request";
    case "response":
      return "response";
    case "diagnostics":
      return "transport";
    default:
      // "events" and null fall back to the inspect/timeline tab.
      return "inspect";
  }
}
