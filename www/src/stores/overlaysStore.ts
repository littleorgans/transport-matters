import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Override } from "../types";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "./persistence";

/**
 * Overlays are persistent, declarative transforms the user wants applied
 * to every exchange captured by this proxy.
 *
 * An overlay is born when the user saves their current breakpoint edits
 * (the live `Override[]` list) as a reusable bundle. The store holds
 * both confirmed overlays and at most one in-flight draft. The draft
 * gate exists so the naming and scope decisions live on the OVERLAYS
 * route surface rather than in a modal over the breakpoint editor.
 *
 * This slice ships only the data model and the draft lifecycle. The
 * apply-at-intercept pipeline, chip strips, and per-field attribution
 * arrive in later slices.
 */
export type OverlayScope = "shared" | { kind: "project"; cwd: string };

/**
 * Placeholder the UI uses when it has no real launch cwd to stamp on a
 * project-scoped overlay. One constant so the eventual "wire up real
 * cwd" slice is a single find-and-replace.
 */
export const UNKNOWN_CWD = "<unknown-cwd>";

export interface Overlay {
  id: string;
  /** Empty string until the user confirms the draft. */
  name: string;
  scope: OverlayScope;
  /** Captured from the breakpoint form at the moment SAVE AS OVERLAY fires. */
  overrides: Override[];
  /** ISO 8601 timestamp. */
  createdAt: string;
  /** True until `confirmDraft` lands; false afterwards. */
  draft: boolean;
}

interface OverlaysState {
  overlays: Overlay[];
  /** At most one draft exists at a time. Null when there is none. */
  draftId: string | null;
  createDraft(overrides: Override[], scope: OverlayScope): string;
  updateDraft(patch: Partial<Pick<Overlay, "name" | "scope">>): void;
  /**
   * Replace the placeholder cwd on the current draft with a resolved
   * one from the backend. No-op unless the draft is project-scoped AND
   * still carrying the sentinel; this keeps later user-driven scope
   * changes from being clobbered once meta lands.
   */
  hydrateDraftCwd(cwd: string): void;
  confirmDraft(): void;
  discardDraft(): void;
  remove(id: string): void;
}

function makeId(): string {
  // crypto.randomUUID is available on all supported Node and browser
  // runtimes (Node 20+, evergreen browsers, jsdom 29+). No fallback
  // branch; callers running under older environments have bigger
  // problems than overlay ids.
  return globalThis.crypto.randomUUID();
}

export const useOverlaysStore = create<OverlaysState>()(
  persist(
    (set, get) => ({
      overlays: [],
      draftId: null,

      createDraft(overrides, scope) {
        const existingDraftId = get().draftId;
        if (existingDraftId) {
          // A second draft replaces the first. Loud in dev so the
          // behavior is visible if UI code ever spawns drafts without
          // first resolving the previous one.
          console.warn(
            "[overlaysStore] createDraft called while a draft already exists; replacing",
            existingDraftId,
          );
        }
        const id = makeId();
        const draft: Overlay = {
          id,
          name: "",
          scope,
          overrides,
          createdAt: new Date().toISOString(),
          draft: true,
        };
        set((s) => ({
          overlays: [...s.overlays.filter((o) => o.id !== existingDraftId), draft],
          draftId: id,
        }));
        return id;
      },

      updateDraft(patch) {
        const draftId = get().draftId;
        if (!draftId) return;
        set((s) => ({
          overlays: s.overlays.map((o) => (o.id === draftId ? { ...o, ...patch } : o)),
        }));
      },

      hydrateDraftCwd(cwd) {
        const draftId = get().draftId;
        if (!draftId) return;
        set((s) => ({
          overlays: s.overlays.map((o) => {
            if (o.id !== draftId) return o;
            if (typeof o.scope !== "object" || o.scope.kind !== "project") return o;
            if (o.scope.cwd !== UNKNOWN_CWD) return o;
            return { ...o, scope: { kind: "project", cwd } };
          }),
        }));
      },

      confirmDraft() {
        const draftId = get().draftId;
        if (!draftId) return;
        set((s) => ({
          overlays: s.overlays.map((o) => (o.id === draftId ? { ...o, draft: false } : o)),
          draftId: null,
        }));
      },

      discardDraft() {
        const draftId = get().draftId;
        if (!draftId) return;
        set((s) => ({
          overlays: s.overlays.filter((o) => o.id !== draftId),
          draftId: null,
        }));
      },

      remove(id) {
        set((s) => ({
          overlays: s.overlays.filter((o) => o.id !== id),
          draftId: s.draftId === id ? null : s.draftId,
        }));
      },
    }),
    {
      name: FRONTEND_STORAGE_KEYS.overlaysStore,
      storage: createFrontendPersistStorage(),
      partialize: (state) => ({
        overlays: state.overlays,
        draftId: state.draftId,
      }),
    },
  ),
);
