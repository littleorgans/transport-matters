import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PausedHeader } from "./PausedHeader";

describe("PausedHeader", () => {
  it("renders the first 8 chars of the flow ID", () => {
    render(
      <PausedHeader
        flowId="abcdefgh-1234-5678"
        pausedAtMs={Date.now()}
        provider="ANTHROPIC"
        model="claude-haiku-4-5-20251001"
        tokensBefore={null}
      />,
    );

    expect(screen.getByText("abcdefgh")).toBeInTheDocument();
  });

  it("renders an em dash when tokensBefore is null", () => {
    render(
      <PausedHeader
        flowId="abcdefgh"
        pausedAtMs={Date.now()}
        provider="ANTHROPIC"
        model="claude-3"
        tokensBefore={null}
      />,
    );

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders a formatted token count when tokensBefore is a number", () => {
    render(
      <PausedHeader
        flowId="abcdefgh"
        pausedAtMs={Date.now()}
        provider="ANTHROPIC"
        model="claude-3"
        tokensBefore={12345}
      />,
    );

    expect(screen.getByText("12,345")).toBeInTheDocument();
  });
});
