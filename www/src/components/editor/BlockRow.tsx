import { useEditableOverride } from "../../hooks/useEditableOverride";
import { ColorizedPre } from "../../lib/colorizeLine";
import type { ContentBlock, Override } from "../../types";
import { CompositeEditableRow, SizeDelta } from "../detail/atoms";
import { blockSummary } from "../detail/ContentBlocks";
import { TextOverrideEditor } from "./TextOverrideEditor";

function blockSize(block: ContentBlock): number {
  return JSON.stringify(block).length;
}

function blockTarget(msgIdx: number, blkIdx: number): string {
  return `msg:${msgIdx}:blk:${blkIdx}`;
}

export function BlockRow({
  block,
  msgIdx,
  blkIdx,
  overrides,
  onOverride,
  expanded,
  onToggleExpanded,
  readOnly,
}: {
  block: ContentBlock;
  msgIdx: number;
  blkIdx: number;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  expanded: boolean;
  onToggleExpanded: () => void;
  /**
   * Read-only mode: the Toggle and textarea are inert (synthesised
   * overrides drive display). Non-text block bodies keep rendering
   * through ColorizedPre — there's no edit to diff against.
   */
  readOnly?: boolean;
}) {
  const target = blockTarget(msgIdx, blkIdx);
  const isText = block.type === "text";

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
    originalValue: isText ? (block as { text: string }).text : "",
    overrides,
    onOverride,
    toggleKind: "message_block_toggle",
    textKind: "message_text",
    target,
    initialExpanded: true,
  });

  // For text blocks the size label expands to ``orig → current`` when
  // the user has edited. Recompute the block JSON with the live text so
  // the delta reflects wire-accurate bytes — not just raw text length.
  // Non-text blocks can only be toggled, not edited; they keep a single
  // size (SizeDelta collapses to the raw number when current === original).
  const baseBlockSize = blockSize(block);
  const currentBlockSize =
    isText && isModified ? JSON.stringify({ ...block, text: localText }).length : baseBlockSize;

  return (
    <CompositeEditableRow
      checked={checked}
      onToggle={handleToggle}
      toggleLabel={`Toggle ${block.type} block`}
      leadingChips={
        <>
          <span className={`chip shrink-0 ${block.type === "thinking" ? "text-lavender" : ""}`}>
            {block.type}
          </span>
          {block.type === "tool_result" && block.is_error && (
            <span className="chip shrink-0 text-rose">error</span>
          )}
        </>
      }
      isModified={isModified}
      preview={blockSummary(block)}
      size={<SizeDelta original={baseBlockSize} current={currentBlockSize} />}
      onToggleExpanded={onToggleExpanded}
      readOnly={readOnly}
    >
      {expanded && (
        <>
          {isText && (
            <div className="mt-2 px-4 pb-1">
              <TextOverrideEditor
                original={block.text}
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
          {block.type === "thinking" && (
            <ColorizedPre text={block.text || JSON.stringify(block.provider_data, null, 2)} />
          )}
          {block.type === "tool_use" && (
            <ColorizedPre text={JSON.stringify(block.input, null, 2)} />
          )}
          {block.type === "tool_result" && (
            <ColorizedPre
              text={block.content
                .map((b) => ("text" in b ? b.text : JSON.stringify(b, null, 2)))
                .join("\n")}
            />
          )}
        </>
      )}
    </CompositeEditableRow>
  );
}
