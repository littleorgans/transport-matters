import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PausedHeader } from "./PausedHeader";

describe("PausedHeader", () => {
  it("renders the first 8 chars of the flow ID", () => {
    render(<PausedHeader flowId="abcdefgh-1234-5678" pausedAtMs={Date.now()} />);

    expect(screen.getByText("abcdefgh")).toBeInTheDocument();
  });
});
