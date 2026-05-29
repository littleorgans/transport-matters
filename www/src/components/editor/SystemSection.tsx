import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import { useEditableOverride } from "../../hooks/useEditableOverride";
import { truncatePreview } from "../../lib/formatting";
import { systemTarget } from "../../lib/overrideTargets";
import { useUIStore } from "../../stores/uiStore";
import type { Override, SystemPart } from "../../types";
import { CompositeEditableRow, MasterBar, SECTION_TONE, SizeDelta } from "../detail/atoms";
import { noopOverride, overrideCountLabel } from "./overrideUtils";
import { TextOverrideEditor } from "./TextOverrideEditor";

interface SystemSectionProps {
  parts: SystemPart[];
  overrides?: Override[];
  onOverride?: (batch: Override[]) => void;
  /**
   * Read-only mode: synthesized overrides drive the display but the
   * toggle/textarea are inert. Used by the Inspect tab so the detail
   * view can reuse the same SystemPartRow shape the editor renders.
   */
  readOnly?: boolean;
}

function SystemPartRow({
  part,
  index,
  overrides,
  onOverride,
  expanded,
  onToggleExpanded,
  readOnly,
}: {
  part: SystemPart;
  index: number;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  expanded: boolean;
  onToggleExpanded: () => void;
  readOnly?: boolean;
}) {
  const target = systemTarget(index);
  const {
    checked,
    isModified,
    localText,
    setLocalText,
    textRef,
    handleToggle,
    commitText,
    handleReset,
  } = useEditableOverride({
    originalValue: part.text,
    overrides,
    onOverride,
    toggleKind: "system_part_toggle",
    textKind: "system_part_text",
    target,
    initialExpanded: true,
  });

  // First-line preview, mirroring the BlockRow treatment for user
  // messages. Trim so a leading newline doesn't render as a blank
  // stub; collapse to ``(empty)`` when the part is whitespace-only.
  const previewSource = part.text.trim();
  const preview = previewSource.length === 0 ? "(empty)" : truncatePreview(previewSource);

  return (
    <CompositeEditableRow
      checked={checked}
      onToggle={handleToggle}
      toggleLabel={`Toggle part ${index}`}
      leadingChips={
        <>
          <span className="chip shrink-0 metric-num">{`[${index}]`}</span>
          {part.cache_hint && <span className="chip shrink-0 text-amber">cached</span>}
        </>
      }
      isModified={isModified}
      preview={preview}
      size={<SizeDelta original={part.text.length} current={localText.length} />}
      onToggleExpanded={onToggleExpanded}
      readOnly={readOnly}
    >
      {expanded && (
        <div className="mt-2 px-4 pb-3">
          <TextOverrideEditor
            original={part.text}
            value={localText}
            onChange={setLocalText}
            onBlur={commitText}
            textareaRef={textRef}
            isModified={isModified}
            onReset={handleReset}
            readOnly={readOnly}
          />
        </div>
      )}
    </CompositeEditableRow>
  );
}

export function SystemSection({
  parts,
  overrides = [],
  onOverride = noopOverride,
  readOnly,
}: SystemSectionProps) {
  const overrideCount = overrides.filter(
    (o) => o.kind === "system_part_toggle" || o.kind === "system_part_text",
  ).length;

  const keyedParts = parts.map((part, idx) => ({
    part,
    idx,
    key: `system-${idx}-${part.text.slice(0, 20)}`,
  }));

  // Seeded from the auto-expand pref in the initializer only, so
  // mid-session flips don't retroactively collapse mounted rows.
  const autoExpandBlocks = useUIStore((s) => s.autoExpandBlocks);
  const { toggleAll, toggleOne, isExpanded } = useCollapsibleSet(parts.length, !autoExpandBlocks);

  // Nothing to show and nothing to edit when the request carries no
  // system parts. Mirrors the early return in ToolsSection and the
  // conditional render the detail view uses in InspectTab, so empty
  // system payloads don't leave a "0 parts" master bar hanging. Placed
  // after hooks to respect React's rules-of-hooks ordering.
  if (parts.length === 0) return null;

  const overrideLabel = overrideCountLabel(overrideCount, readOnly);

  return (
    <section className="space-y-4">
      <div className="card-flush">
        <MasterBar
          label="system"
          tone={SECTION_TONE.system}
          count={parts.length}
          countUnit="part"
          extras={
            overrideCount > 0 ? (
              <>
                <span className="h-1 w-1 rounded-full bg-amber" />
                <span className="label text-amber">
                  {overrideCount} {overrideLabel}
                </span>
              </>
            ) : undefined
          }
          onToggleAll={toggleAll}
        />
        <div className="hairline-x" />
        <div>
          {keyedParts.map((entry, i) => (
            <div key={entry.key}>
              <SystemPartRow
                part={entry.part}
                index={entry.idx}
                overrides={overrides}
                onOverride={onOverride}
                expanded={isExpanded(entry.idx)}
                onToggleExpanded={() => toggleOne(entry.idx)}
                readOnly={readOnly}
              />
              {i < keyedParts.length - 1 && <div className="hairline-x mx-4" />}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
