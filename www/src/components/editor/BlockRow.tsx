import { useEditableOverride } from "../../hooks/useEditableOverride";
import { ColorizedPre } from "../../lib/colorizeLine";
import type { ContentBlock, Override } from "../../types";
import { Chevron, inputClass, OriginalPreview } from "../detail/atoms";
import { Toggle } from "../Toggle";

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
}: {
  block: ContentBlock;
  msgIdx: number;
  blkIdx: number;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  const target = blockTarget(msgIdx, blkIdx);
  const isText = block.type === "text";

  const { checked, isModified, localText, setLocalText, textRef, handleToggle, commitText } =
    useEditableOverride({
      originalValue: isText ? (block as { text: string }).text : "",
      overrides,
      onOverride,
      toggleKind: "message_block_toggle",
      textKind: "message_text",
      target,
      initialExpanded: true,
    });

  return (
    <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
      {/* Block header — clickable strip that folds the body. The Toggle
          sits in its own stopPropagation island so flipping the applied
          state never inadvertently collapses the block (and vice versa). */}
      {/* biome-ignore lint/a11y/useSemanticElements: composite row wraps a Toggle button; button-in-button is invalid HTML */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggleExpanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggleExpanded();
          }
        }}
        className="flex cursor-pointer items-start gap-3 px-4 py-2.5 transition-colors hover:bg-raised focus:outline-none focus-visible:bg-raised"
      >
        {/* biome-ignore lint/a11y/useKeyWithClickEvents: stopPropagation wrapper, the inner Toggle handles its own keyboard events */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: click-swallow wrapper isolates the Toggle from the row's expand handler */}
        <div className="-mt-0.75" onClick={(e) => e.stopPropagation()}>
          <Toggle checked={checked} onChange={handleToggle} label={`Toggle ${block.type} block`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <span className={`chip ${block.type === "thinking" ? "text-lavender" : ""}`}>
              {block.type}
            </span>
            <span className="label text-txt-3 metric-num">{blockSize(block).toLocaleString()}</span>
            {block.type === "tool_result" && block.is_error && (
              <span className="chip text-rose">error</span>
            )}
            {isModified && <span className="h-1 w-1 rounded-full bg-amber" />}
          </div>
        </div>
        <Chevron expanded={expanded} />
      </div>
      {expanded && (
        <>
          {isText && (
            <div className="mt-2 space-y-2 px-4 pb-1">
              <textarea
                ref={textRef}
                className={inputClass}
                value={localText}
                onChange={(e) => setLocalText(e.target.value)}
                onBlur={commitText}
              />
              {isModified && <OriginalPreview text={block.text} />}
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
    </div>
  );
}
