import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { exchangeProps } = vi.hoisted(() => ({ exchangeProps: vi.fn() }));

vi.mock("../../../components/ExchangeDetail", () => ({
  ExchangeDetail: (props: { id: string; initialTab?: string; onMissing?: () => void }) => {
    exchangeProps(props);
    return (
      <div
        data-id={props.id}
        data-onmissing={typeof props.onMissing}
        data-tab={props.initialTab}
        data-testid="exchange-detail"
      />
    );
  },
}));

// Imported after the mock so the viewer picks up the stubbed ExchangeDetail.
const { ProviderExchangeResourceViewer } = await import("./ProviderExchangeResourceViewer");

describe("ProviderExchangeResourceViewer", () => {
  it("reuses ExchangeDetail with the exchange id and a no-op onMissing (no legacy route coupling)", () => {
    render(<ProviderExchangeResourceViewer runId="run-current" exchangeId="ex-1" />);
    const detail = screen.getByTestId("exchange-detail");
    expect(detail).toHaveAttribute("data-id", "ex-1");
    // onMissing is supplied, so ExchangeDetail never falls back to mutating the
    // legacy uiStore selection — the canvas stays decoupled from route state.
    expect(detail).toHaveAttribute("data-onmissing", "function");
    const props = exchangeProps.mock.calls.at(-1)?.[0] as { onMissing: () => void };
    expect(() => props.onMissing()).not.toThrow();
  });

  it("maps initialView onto the ExchangeDetail tab", () => {
    const cases: Array<[string | null | undefined, string]> = [
      ["request", "request"],
      ["response", "response"],
      ["diagnostics", "transport"],
      ["events", "inspect"],
      [null, "inspect"],
      [undefined, "inspect"],
    ];
    for (const [initialView, expectedTab] of cases) {
      const { unmount } = render(
        <ProviderExchangeResourceViewer
          runId="run-current"
          exchangeId="ex-2"
          initialView={initialView}
        />,
      );
      expect(screen.getByTestId("exchange-detail")).toHaveAttribute("data-tab", expectedTab);
      unmount();
    }
  });
});
