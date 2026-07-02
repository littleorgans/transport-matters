import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { legacyClaudeRes, makeEntry } from "./__test-utils__/exchangeList";
import { ExchangeTurnCard } from "./ExchangeTurnCard";

vi.mock("../hooks/useTurnContent", () => ({
  useTurnContent: vi.fn(() => ({
    data: { response_text: "response", stop_reason: "end_turn", user_text: "prompt" },
    isLoading: false,
  })),
}));

describe("ExchangeTurnCard", () => {
  it("renders the shared relative age for settled rows", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-29T12:00:00.000Z"));
    try {
      const entry = makeEntry({
        id: "settled-age",
        res: legacyClaudeRes,
        ts: "2026-05-29T11:55:00.000Z",
      });

      render(
        <ExchangeTurnCard
          runId="run-current"
          entry={entry}
          depth={0}
          isHistorical={false}
          isSelected={false}
          previewWaiting={false}
          index={0}
          offsetTop={0}
          onSelect={() => {}}
        />,
      );

      expect(screen.getByTestId("exchange-time-settled-age")).toHaveTextContent("5m ago");
    } finally {
      vi.useRealTimers();
    }
  });
});
