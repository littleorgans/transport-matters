import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Override } from "../types";
import { UNKNOWN_CWD, useOverlaysStore } from "./overlaysStore";

const toolToggle: Override = { kind: "tool_toggle", target: "Read", value: false };
const systemEdit: Override = { kind: "system_part_text", target: "sys:0", value: "hi" };

beforeEach(() => {
  useOverlaysStore.setState({ overlays: [], draftId: null });
});

describe("overlaysStore", () => {
  describe("createDraft", () => {
    it("creates a draft overlay with the captured overrides and scope", () => {
      const id = useOverlaysStore
        .getState()
        .createDraft([toolToggle], { kind: "project", cwd: "/tmp/app" });
      const state = useOverlaysStore.getState();
      expect(state.draftId).toBe(id);
      expect(state.overlays).toHaveLength(1);
      const overlay = state.overlays[0];
      expect(overlay?.id).toBe(id);
      expect(overlay?.draft).toBe(true);
      expect(overlay?.name).toBe("");
      expect(overlay?.overrides).toEqual([toolToggle]);
      expect(overlay?.scope).toEqual({ kind: "project", cwd: "/tmp/app" });
      expect(overlay?.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    });

    it("replaces an existing draft and logs a warning", () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
      const firstId = useOverlaysStore.getState().createDraft([toolToggle], "shared");
      const secondId = useOverlaysStore.getState().createDraft([systemEdit], "shared");

      const state = useOverlaysStore.getState();
      expect(state.draftId).toBe(secondId);
      expect(state.overlays).toHaveLength(1);
      expect(state.overlays[0]?.id).toBe(secondId);
      expect(state.overlays.some((o) => o.id === firstId)).toBe(false);
      expect(warnSpy).toHaveBeenCalled();
      warnSpy.mockRestore();
    });
  });

  describe("updateDraft", () => {
    it("patches the draft name and scope", () => {
      useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().updateDraft({ name: "only core tools" });
      useOverlaysStore.getState().updateDraft({ scope: { kind: "project", cwd: "/home/me/repo" } });

      const draft = useOverlaysStore.getState().overlays[0];
      expect(draft?.name).toBe("only core tools");
      expect(draft?.scope).toEqual({ kind: "project", cwd: "/home/me/repo" });
    });

    it("is a no-op when there is no draft", () => {
      useOverlaysStore.getState().updateDraft({ name: "ghost" });
      expect(useOverlaysStore.getState().overlays).toHaveLength(0);
    });
  });

  describe("confirmDraft", () => {
    it("flips draft flag off and clears draftId", () => {
      useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().updateDraft({ name: "saved" });
      useOverlaysStore.getState().confirmDraft();

      const state = useOverlaysStore.getState();
      expect(state.draftId).toBeNull();
      expect(state.overlays).toHaveLength(1);
      expect(state.overlays[0]?.draft).toBe(false);
      expect(state.overlays[0]?.name).toBe("saved");
    });

    it("is a no-op when there is no draft", () => {
      useOverlaysStore.getState().confirmDraft();
      expect(useOverlaysStore.getState().overlays).toHaveLength(0);
    });
  });

  describe("discardDraft", () => {
    it("removes the draft and clears draftId", () => {
      useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().discardDraft();

      const state = useOverlaysStore.getState();
      expect(state.draftId).toBeNull();
      expect(state.overlays).toHaveLength(0);
    });

    it("leaves confirmed overlays in place", () => {
      useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().updateDraft({ name: "keep me" });
      useOverlaysStore.getState().confirmDraft();
      useOverlaysStore.getState().createDraft([systemEdit], "shared");
      useOverlaysStore.getState().discardDraft();

      const state = useOverlaysStore.getState();
      expect(state.draftId).toBeNull();
      expect(state.overlays).toHaveLength(1);
      expect(state.overlays[0]?.name).toBe("keep me");
    });
  });

  describe("hydrateDraftCwd", () => {
    it("replaces the UNKNOWN_CWD sentinel on a project-scoped draft", () => {
      useOverlaysStore.getState().createDraft([toolToggle], { kind: "project", cwd: UNKNOWN_CWD });
      useOverlaysStore.getState().hydrateDraftCwd("/Users/me/repo");

      const draft = useOverlaysStore.getState().overlays[0];
      expect(draft?.scope).toEqual({ kind: "project", cwd: "/Users/me/repo" });
    });

    it("leaves an already-resolved cwd untouched", () => {
      useOverlaysStore.getState().createDraft([toolToggle], { kind: "project", cwd: "/tmp/app" });
      useOverlaysStore.getState().hydrateDraftCwd("/Users/me/repo");

      const draft = useOverlaysStore.getState().overlays[0];
      expect(draft?.scope).toEqual({ kind: "project", cwd: "/tmp/app" });
    });

    it("is a no-op on a shared-scoped draft", () => {
      useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().hydrateDraftCwd("/Users/me/repo");

      const draft = useOverlaysStore.getState().overlays[0];
      expect(draft?.scope).toBe("shared");
    });

    it("is a no-op when there is no draft", () => {
      useOverlaysStore.getState().hydrateDraftCwd("/Users/me/repo");
      expect(useOverlaysStore.getState().overlays).toHaveLength(0);
    });
  });

  describe("remove", () => {
    it("removes a confirmed overlay by id", () => {
      useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().updateDraft({ name: "one" });
      useOverlaysStore.getState().confirmDraft();
      const confirmedId = useOverlaysStore.getState().overlays[0]?.id;
      expect(confirmedId).toBeDefined();

      useOverlaysStore.getState().remove(confirmedId as string);
      expect(useOverlaysStore.getState().overlays).toHaveLength(0);
    });

    it("clears draftId when removing the active draft", () => {
      const id = useOverlaysStore.getState().createDraft([toolToggle], "shared");
      useOverlaysStore.getState().remove(id);
      const state = useOverlaysStore.getState();
      expect(state.draftId).toBeNull();
      expect(state.overlays).toHaveLength(0);
    });
  });
});
