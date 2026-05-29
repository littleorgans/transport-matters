import { useEffect, useRef, useState } from "react";
import { useMeta } from "../../hooks/useMeta";
import { pluralize } from "../../lib/formatting";
import { type Overlay, UNKNOWN_CWD, useOverlaysStore } from "../../stores/overlaysStore";
import type { Override, OverrideKind } from "../../types";
import { TransportMattersIcon } from "../TransportMattersIcon";

const RESOLVING_CWD_LABEL = "resolving workspace\u2026";

/**
 * OVERLAYS: a librarian's view of the user's persistent transforms.
 *
 * Three states share this panel:
 *   1. Empty: no overlays, no draft. Atmospheric placeholder with an
 *             amber instruction line pointing at the breakpoint flow.
 *   2. Draft: exactly one draft exists. Centered card asks for a name
 *             and scope, then commits via CONFIRM or reverts via DISCARD.
 *   3. List:  one or more confirmed overlays. Lightweight table with
 *             scope chip, created-at, and a row-hover DELETE action.
 *
 * The apply-at-intercept pipeline does not live here yet. This view is
 * pure curation: names, scopes, and lifecycle only.
 */

type Stage = "empty" | "draft" | "list";

function resolveStage(draft: Overlay | undefined, confirmed: Overlay[]): Stage {
  if (draft) return "draft";
  if (confirmed.length === 0) return "empty";
  return "list";
}

/** Human-readable singular/plural captions for every override kind. */
const KIND_LABELS: Record<OverrideKind, { singular: string; plural: string }> = {
  tool_toggle: { singular: "tool toggle", plural: "tool toggles" },
  tool_description: { singular: "tool description edit", plural: "tool description edits" },
  system_part_toggle: { singular: "system part toggle", plural: "system part toggles" },
  system_part_text: { singular: "system part edit", plural: "system part edits" },
  message_block_toggle: { singular: "message block toggle", plural: "message block toggles" },
  message_text: { singular: "message edit", plural: "message edits" },
  truncate_tool_result: {
    singular: "truncate tool-result rule",
    plural: "truncate tool-result rules",
  },
  sampling_set: { singular: "sampling field edit", plural: "sampling field edits" },
  provider_extras_set: { singular: "provider extras edit", plural: "provider extras edits" },
};

const KIND_ORDER: readonly OverrideKind[] = [
  "tool_toggle",
  "tool_description",
  "system_part_toggle",
  "system_part_text",
  "message_block_toggle",
  "message_text",
  "truncate_tool_result",
  "sampling_set",
  "provider_extras_set",
];

function summarizeOverrides(overrides: Override[]): string {
  const counts = new Map<OverrideKind, number>();
  for (const o of overrides) {
    counts.set(o.kind, (counts.get(o.kind) ?? 0) + 1);
  }
  if (counts.size === 0) return "No captured overrides";
  const parts: string[] = [];
  for (const kind of KIND_ORDER) {
    const n = counts.get(kind) ?? 0;
    if (n === 0) continue;
    const label = KIND_LABELS[kind];
    parts.push(pluralize(n, label.singular, label.plural));
  }
  return parts.join(", ");
}

function formatCreatedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = Date.now();
  const diffMs = now - d.getTime();
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) return "just now";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)}m ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}h ago`;
  if (diffMs < 7 * day) return `${Math.floor(diffMs / day)}d ago`;
  return d.toISOString().slice(0, 10);
}

function Atmosphere() {
  return (
    <div
      aria-hidden
      className="absolute inset-0 flex items-center justify-center text-edge-subtle opacity-30 pointer-events-none"
    >
      <TransportMattersIcon className="spin-gentle h-[90vh] w-[90vh]" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="relative h-full overflow-hidden">
      <Atmosphere />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-7 px-8 text-center">
        <div className="flex flex-col items-center gap-4">
          <TransportMattersIcon className="h-[64px] w-[64px] text-txt shrink-0" />
          <h2 className="text-[18px] font-semibold tracking-[0.22em] text-txt uppercase">
            Overlays
          </h2>
          <span className="label text-[12px]">Persistent transforms</span>
        </div>
        <p className="max-w-[500px] text-[14px] leading-[1.7] text-txt-3">
          Overlays are declarative rules that reshape every exchange captured by this proxy. Start
          by editing a paused request in the breakpoint form, then press SAVE AS OVERLAY to turn
          that edit into something reusable.
        </p>
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-[0.22em] text-amber">
          <span aria-hidden className="h-1 w-1 rounded-full bg-amber" />
          <span>Save a breakpoint edit to begin</span>
        </div>
      </div>
    </div>
  );
}

function DraftState({ draft }: { draft: Overlay }) {
  const updateDraft = useOverlaysStore((s) => s.updateDraft);
  const hydrateDraftCwd = useOverlaysStore((s) => s.hydrateDraftCwd);
  const confirmDraft = useOverlaysStore((s) => s.confirmDraft);
  const discardDraft = useOverlaysStore((s) => s.discardDraft);
  const { meta } = useMeta();
  const [name, setName] = useState(draft.name);
  const [scope, setScope] = useState<Overlay["scope"]>(draft.scope);
  const nameRef = useRef<HTMLInputElement>(null);

  // Autofocus the name field on mount so the user lands on the single
  // empty input with no extra click. Running only on mount is intentional;
  // re-focusing on every draft change would fight the user during typing.
  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Replace the UNKNOWN_CWD sentinel with the real cwd once meta lands.
  // No-op if the draft already holds a resolved cwd, is shared-scoped,
  // or if meta is still loading. Keeping the hydration effect-driven
  // means the prefetch in main.tsx is the happy path; a cold click just
  // re-renders cleanly once the query resolves.
  useEffect(() => {
    if (!meta?.cwd) return;
    if (typeof draft.scope !== "object") return;
    if (draft.scope.kind !== "project") return;
    if (draft.scope.cwd !== UNKNOWN_CWD) return;
    hydrateDraftCwd(meta.cwd);
  }, [meta?.cwd, draft.scope, hydrateDraftCwd]);

  const trimmed = name.trim();
  const canConfirm = trimmed.length > 0;
  const projectCwd = typeof scope === "object" ? scope.cwd : null;
  const projectCwdResolved = projectCwd && projectCwd !== UNKNOWN_CWD ? projectCwd : null;
  const projectCwdDisplay = projectCwdResolved ?? meta?.cwd ?? RESOLVING_CWD_LABEL;
  const summary = summarizeOverrides(draft.overrides);

  const selectProject = () => {
    // Prefer an already-resolved cwd (rare but possible: a previous
    // session hydrated the draft before a store-only refresh), then
    // meta.cwd (warm path from the app-mount prefetch), then the
    // placeholder. The hydration effect above will swap a placeholder
    // out as soon as meta resolves.
    const nextCwd = projectCwdResolved ?? meta?.cwd ?? UNKNOWN_CWD;
    const next: Overlay["scope"] = { kind: "project", cwd: nextCwd };
    setScope(next);
    updateDraft({ scope: next });
  };

  const selectShared = () => {
    setScope("shared");
    updateDraft({ scope: "shared" });
  };

  const handleNameChange = (value: string) => {
    setName(value);
    updateDraft({ name: value });
  };

  const handleConfirm = () => {
    if (!canConfirm) return;
    // Persist the trimmed name before confirming so the committed overlay
    // never carries trailing whitespace the user did not intend.
    updateDraft({ name: trimmed });
    confirmDraft();
  };

  return (
    <div className="relative h-full overflow-hidden">
      <Atmosphere />
      <div className="absolute inset-0 flex items-center justify-center px-8">
        <div className="card w-full max-w-[520px] p-6 space-y-5">
          <div className="flex items-center gap-3">
            <span aria-hidden className="h-1 w-1 rounded-full bg-amber" />
            <h2 className="text-[13px] font-semibold tracking-[0.22em] text-amber uppercase">
              New overlay
            </h2>
          </div>

          <label className="flex flex-col gap-2">
            <span className="label">Name</span>
            <input
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="e.g. only core tools"
              aria-label="Overlay name"
              className="border border-edge bg-canvas px-3 py-2 text-[14px] text-txt placeholder:text-txt-3 focus:border-amber/60 focus:outline-none"
            />
          </label>

          <fieldset className="flex flex-col gap-2">
            <legend className="label">Scope</legend>
            <label className="flex cursor-pointer items-center gap-3 border border-edge bg-canvas px-3 py-2 hover:border-edge-strong">
              <input
                type="radio"
                name="overlay-scope"
                checked={typeof scope === "object" && scope.kind === "project"}
                onChange={selectProject}
                className="accent-amber"
              />
              <span className="text-[13px] text-txt">Project only</span>
              <span className="label font-mono normal-case tracking-normal text-txt-3 ml-auto truncate">
                {projectCwdDisplay}
              </span>
            </label>
            <label className="flex cursor-pointer items-center gap-3 border border-edge bg-canvas px-3 py-2 hover:border-edge-strong">
              <input
                type="radio"
                name="overlay-scope"
                checked={scope === "shared"}
                onChange={selectShared}
                className="accent-teal"
              />
              <span className="text-[13px] text-txt">Shared</span>
              <span className="label text-txt-3 ml-auto">Every project</span>
            </label>
          </fieldset>

          <div className="flex items-start gap-3 border border-edge-subtle bg-canvas px-3 py-2.5">
            <span className="label shrink-0">Captures</span>
            <span className="text-[13px] text-txt-2 leading-[1.5]">{summary}</span>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={discardDraft}
              className="btn cursor-pointer border border-edge bg-surface px-4 py-2 text-[12px] font-medium uppercase tracking-[0.14em] text-txt-2 hover:bg-raised hover:text-txt"
            >
              Discard
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={!canConfirm}
              className="btn cursor-pointer border border-amber/40 bg-amber/10 px-4 py-2 text-[12px] font-medium uppercase tracking-[0.14em] text-amber hover:bg-amber/20 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-amber/10"
            >
              Confirm
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ScopeChip({ scope }: { scope: Overlay["scope"] }) {
  if (scope === "shared") {
    return <span className="chip border-teal/30 text-teal">Shared</span>;
  }
  return <span className="chip border-amber/30 text-amber">Project</span>;
}

function ListState({ overlays }: { overlays: Overlay[] }) {
  const remove = useOverlaysStore((s) => s.remove);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[760px] px-8 py-10 space-y-6">
        <header className="section-rule">
          <h2 className="label text-amber">
            Overlays
            <span className="ml-2 metric-num tabular-nums text-txt-3">({overlays.length})</span>
          </h2>
        </header>

        <div className="card divide-y divide-edge">
          {overlays.map((overlay) => {
            const cwd = typeof overlay.scope === "object" ? overlay.scope.cwd : null;
            return (
              <div
                key={overlay.id}
                className="group flex items-center gap-4 px-5 py-3 hover:bg-raised"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] text-txt truncate">{overlay.name}</span>
                    <ScopeChip scope={overlay.scope} />
                  </div>
                  {cwd && (
                    <div className="mt-1 label font-mono normal-case tracking-normal text-txt-3 truncate">
                      {cwd}
                    </div>
                  )}
                </div>
                <span className="label metric-num tabular-nums text-txt-3 shrink-0">
                  {formatCreatedAt(overlay.createdAt)}
                </span>
                <button
                  type="button"
                  onClick={() => remove(overlay.id)}
                  aria-label={`Delete overlay ${overlay.name}`}
                  className="btn cursor-pointer border border-rose/25 bg-rose/5 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.14em] text-rose/80 opacity-0 transition-opacity hover:bg-rose/12 hover:text-rose group-hover:opacity-100 focus:opacity-100"
                >
                  Delete
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function OverlaysView() {
  const overlays = useOverlaysStore((s) => s.overlays);
  const draftId = useOverlaysStore((s) => s.draftId);
  const draft = draftId ? overlays.find((o) => o.id === draftId) : undefined;
  const confirmed = overlays.filter((o) => !o.draft);
  const stage = resolveStage(draft, confirmed);

  if (stage === "draft" && draft) return <DraftState draft={draft} />;
  if (stage === "list") return <ListState overlays={confirmed} />;
  return <EmptyState />;
}
