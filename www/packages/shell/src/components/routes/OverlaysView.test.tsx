import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Meta } from "../../api";
import { UNKNOWN_CWD, useOverlaysStore } from "../../stores/overlaysStore";
import type { Override } from "../../types";
import { OverlaysView } from "./OverlaysView";

const toolToggle: Override = { kind: "tool_toggle", target: "Read", value: false };
const systemEdit: Override = { kind: "system_part_text", target: "sys:0", value: "hi" };

// Control what useMeta returns per test. Default is a resolved meta so
// DraftState renders its steady state; individual tests can override
// before mounting to exercise the "cold" (undefined) or "hydrate"
// transitions.
const mockMeta: { value: Meta | undefined } = { value: undefined };
vi.mock("../../hooks/useMeta", () => ({
  useMeta: () => ({ meta: mockMeta.value, isLoading: mockMeta.value === undefined }),
}));

beforeEach(() => {
  useOverlaysStore.setState({ overlays: [], draftId: null });
  mockMeta.value = {
    channel: "stable",
    channelBadge: null,
    channelLabel: "Stable",
    cwd: "/tmp/fake",
    harnesses: [],
    workspaceId: "fake/abc123",
    spaceId: null,
    worktreeId: null,
    transcriptDenylist: [],
  };
});

describe("OverlaysView: empty state", () => {
  it("renders the title and the amber begin instruction", () => {
    render(<OverlaysView />);
    expect(screen.getByRole("heading", { name: /Overlays/ })).toBeInTheDocument();
    expect(screen.getByText("Persistent transforms")).toBeInTheDocument();
    expect(screen.getByText(/Save a breakpoint edit to begin/)).toBeInTheDocument();
  });
});

describe("OverlaysView: draft state", () => {
  beforeEach(() => {
    useOverlaysStore
      .getState()
      .createDraft([toolToggle, systemEdit], { kind: "project", cwd: "/tmp/app" });
  });

  it("renders the name input and disables confirm until filled", () => {
    render(<OverlaysView />);
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled();

    const input = screen.getByLabelText("Overlay name");
    fireEvent.change(input, { target: { value: "only core tools" } });
    expect(confirm).not.toBeDisabled();
  });

  it("whitespace-only names do not enable confirm", () => {
    render(<OverlaysView />);
    fireEvent.change(screen.getByLabelText("Overlay name"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
  });

  it("confirm moves the overlay into the list state", () => {
    render(<OverlaysView />);
    fireEvent.change(screen.getByLabelText("Overlay name"), {
      target: { value: "only core tools" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(screen.getByText("only core tools")).toBeInTheDocument();
    expect(useOverlaysStore.getState().draftId).toBeNull();
    expect(useOverlaysStore.getState().overlays[0]?.draft).toBe(false);
  });

  it("discard clears the draft and returns to the empty state", () => {
    render(<OverlaysView />);
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));

    expect(screen.queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
    expect(useOverlaysStore.getState().overlays).toHaveLength(0);
    expect(screen.getByText(/Save a breakpoint edit to begin/)).toBeInTheDocument();
  });

  it("summarises captured overrides by kind", () => {
    render(<OverlaysView />);
    // One tool_toggle + one system_part_text in the seeded draft.
    expect(screen.getByText(/1 tool toggle/)).toBeInTheDocument();
    expect(screen.getByText(/1 system part edit/)).toBeInTheDocument();
  });

  it("shows the draft's own cwd in the project scope label when it is already resolved", () => {
    // Seed draft carries /tmp/app; meta points elsewhere. The display
    // must prefer the draft's own cwd — meta is only a fallback for
    // drafts still carrying UNKNOWN_CWD, and clobbering a resolved cwd
    // would break the "I picked this project" contract.
    render(<OverlaysView />);
    expect(screen.getByText("/tmp/app")).toBeInTheDocument();
    expect(screen.queryByText("/tmp/fake")).not.toBeInTheDocument();
  });

  it("hydrates a draft stamped with UNKNOWN_CWD once meta arrives", async () => {
    // Seed a second draft that carries the sentinel, mirroring the
    // cold-click path in EditorActions where meta had not resolved
    // at the moment SAVE AS OVERLAY fired.
    useOverlaysStore.setState({ overlays: [], draftId: null });
    useOverlaysStore.getState().createDraft([toolToggle], { kind: "project", cwd: UNKNOWN_CWD });

    render(<OverlaysView />);

    await waitFor(() => {
      const draft = useOverlaysStore.getState().overlays[0];
      expect(draft?.scope).toEqual({ kind: "project", cwd: "/tmp/fake" });
    });
    expect(screen.getByText("/tmp/fake")).toBeInTheDocument();
  });

  it("shows the resolving placeholder while meta is loading", () => {
    // Override before mount: meta is undefined. The sentinel must not
    // leak into the UI in this transient state.
    useOverlaysStore.setState({ overlays: [], draftId: null });
    useOverlaysStore.getState().createDraft([toolToggle], { kind: "project", cwd: UNKNOWN_CWD });
    mockMeta.value = undefined;

    render(<OverlaysView />);
    expect(screen.getByText(/resolving workspace/)).toBeInTheDocument();
    expect(screen.queryByText(UNKNOWN_CWD)).not.toBeInTheDocument();
  });
});

describe("OverlaysView: list state", () => {
  beforeEach(() => {
    useOverlaysStore.getState().createDraft([toolToggle], { kind: "project", cwd: "/tmp/app" });
    useOverlaysStore.getState().updateDraft({ name: "only core tools" });
    useOverlaysStore.getState().confirmDraft();
  });

  it("renders the confirmed overlay with a scope chip", () => {
    render(<OverlaysView />);
    expect(screen.getByText("only core tools")).toBeInTheDocument();
    expect(screen.getByText("Project")).toBeInTheDocument();
  });

  it("delete button removes the overlay", () => {
    render(<OverlaysView />);
    const del = screen.getByRole("button", { name: /Delete overlay/ });
    fireEvent.click(del);
    expect(useOverlaysStore.getState().overlays).toHaveLength(0);
  });
});
