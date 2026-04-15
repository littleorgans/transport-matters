import { diffLines } from "diff";
import { type Ref, useEffect, useMemo, useRef, useState } from "react";
import { inputClass } from "../detail/atoms";

// Single-panel editor for text overrides across the Breakpoint editor
// (system parts, user/assistant text blocks, tool descriptions). When
// there's no override yet, it's just the textarea — no chrome, no
// tabs, no RESET. Once the user has committed a change (``isModified``
// flips true), a ``EDIT | DIFF`` tab bar appears with RESET on the
// right edge, and the single panel swaps between the textarea and an
// inline line-level diff.
//
// Line granularity matches git's default output. Word-level diffs
// produced a visually noisy collage of strikethroughs and additions
// when the same paragraph was rewritten; whole-line removed/added
// blocks scan cleanly and are also what users' muscle memory from
// ``git diff`` expects.
//
// Why the tab bar: collapsing the older "textarea on top, ORIGINAL/diff
// pre below" dual-panel freed a ton of vertical space and put the
// reset action next to the edit surface it undoes. RESET sat on the
// row header before, where it was easy to miss next to the modified
// dot; moving it into the tab bar both clusters it with the other
// edit-mode controls and keeps the row header quiet for scanning.

interface TextOverrideEditorProps {
  /** The pristine value from the upstream payload — what a reset would restore. */
  original: string;
  /** Current draft the textarea binds to (typically the hook's ``localText``). */
  value: string;
  onChange: (next: string) => void;
  /** Commit hook — fires on blur so the override store reconciles against ``original``. */
  onBlur: () => void;
  /** Ref threaded through to the textarea so the auto-size effect in ``useEditableOverride`` can measure. */
  textareaRef: Ref<HTMLTextAreaElement>;
  isModified: boolean;
  onReset: () => void;
}

export function TextOverrideEditor({
  original,
  value,
  onChange,
  onBlur,
  textareaRef,
  isModified,
  onReset,
}: TextOverrideEditorProps) {
  const [view, setView] = useState<"edit" | "diff">("edit");

  // When modifications clear — user clicked RESET, or the override
  // was dropped externally — snap the tab back to EDIT so the next
  // round of typing doesn't land in a now-stale DIFF view.
  const prevModifiedRef = useRef(isModified);
  useEffect(() => {
    if (prevModifiedRef.current && !isModified) {
      setView("edit");
    }
    prevModifiedRef.current = isModified;
  }, [isModified]);

  // Skip the diff entirely while EDIT is active. Line-level Myers is
  // fast enough (``diffLines`` operates on a few hundred lines, not
  // thousands of words) that a run-per-keystroke would likely be fine,
  // but DIFF is a read-only tab so a fresh compute is only needed when
  // the user switches into it.
  const parts = useMemo(() => {
    if (!isModified || view !== "diff") return null;
    return diffLines(original, value);
  }, [original, value, isModified, view]);

  if (!isModified) {
    return (
      <textarea
        ref={textareaRef}
        className={inputClass}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
      />
    );
  }

  return (
    <div>
      {/* Tab bar — mirrors the BreakpointEditor main tab bar
          (``tab-pressed`` / ``tab-rest``) but at 11px so the nested
          scope reads as per-row, not competing with the page tabs.
          RESET floats to the right edge inside the same strip. */}
      <div role="tablist" className="flex items-stretch border-y border-edge">
        <button
          type="button"
          role="tab"
          aria-selected={view === "edit"}
          onClick={(e) => {
            e.stopPropagation();
            setView("edit");
          }}
          className={`cursor-pointer px-4 py-2 text-[11px] font-medium uppercase tracking-[0.14em] transition-all duration-150 ${
            view === "edit" ? "tab-pressed text-txt" : "tab-rest text-txt-3 hover:text-txt-2"
          }`}
        >
          Edit
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "diff"}
          onClick={(e) => {
            e.stopPropagation();
            setView("diff");
          }}
          className={`cursor-pointer px-4 py-2 text-[11px] font-medium uppercase tracking-[0.14em] transition-all duration-150 ${
            view === "diff" ? "tab-pressed text-txt" : "tab-rest text-txt-3 hover:text-txt-2"
          }`}
        >
          Diff
        </button>
        <div className="flex flex-1 tab-rest items-center justify-end pr-3">
          <button
            type="button"
            aria-label="Reset text override"
            onClick={(e) => {
              e.stopPropagation();
              onReset();
            }}
            className="label cursor-pointer text-txt-3 transition-colors hover:text-amber"
          >
            reset
          </button>
        </div>
      </div>
      {view === "edit" ? (
        <textarea
          ref={textareaRef}
          className={inputClass}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
        />
      ) : (
        <pre className="bg-canvas p-3 text-[12px] whitespace-pre-wrap border border-edge font-mono">
          {parts?.map((part, i) => {
            // Stable-enough key within a single render. Parts are
            // regenerated each time inputs change, so React reconciles
            // by position anyway; we just need local uniqueness.
            const key = `${i}-${part.value.slice(0, 16)}`;
            if (part.added) {
              return (
                <ins key={key} className="bg-sage/15 text-sage no-underline">
                  {part.value}
                </ins>
              );
            }
            if (part.removed) {
              return (
                <del key={key} className="bg-rose/15 text-rose decoration-rose/70">
                  {part.value}
                </del>
              );
            }
            return (
              <span key={key} className="text-txt-3">
                {part.value}
              </span>
            );
          })}
        </pre>
      )}
    </div>
  );
}
