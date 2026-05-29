import { useMemo } from "react";
import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import { overrideValue } from "../../lib/overrides";
import { messageBlockTarget, toolResultTarget } from "../../lib/overrideTargets";
import { useUIStore } from "../../stores/uiStore";
import type { Message, Override } from "../../types";
import { MasterBar, SECTION_TONE } from "../detail/atoms";
import { blockKey } from "../detail/ContentBlocks";
import { BlockRow } from "./BlockRow";
import { noopOverride, overrideCountLabel } from "./overrideUtils";

interface MessagesSectionProps {
  messages: Message[];
  overrides?: Override[];
  onOverride?: (batch: Override[]) => void;
  /**
   * Read-only mode: synthesised overrides drive the display but the
   * per-block Toggle and text editor are inert. The pair-tandem
   * wrapper is also skipped — curated overrides already reflect the
   * post-pipeline state, so there's no half-toggle to synthesise a
   * twin for. Used by the Inspect tab.
   */
  readOnly?: boolean;
}

function toolResultBlockTarget(message: Message, blkIdx: number): string | null {
  const block = message.content[blkIdx];
  return block?.type === "tool_result" ? toolResultTarget(block.tool_use_id) : null;
}

/**
 * Walk every message and emit a target -> pairTarget map for tool_use
 * and tool_result block pairs (matched on `id` / `tool_use_id`). Any
 * `message_block_toggle` aimed at one half of a pair must move the
 * other half in tandem; otherwise the curated payload ends up with an
 * orphan, which the Anthropic API rejects with `unexpected tool_use_id
 * found in tool_result blocks`. The map is bidirectional so a single
 * lookup serves either toggle direction.
 */
function buildPairMap(messages: Message[]): Map<string, string> {
  const useLoc = new Map<string, string>();
  const resultLoc = new Map<string, string>();
  messages.forEach((msg, m) => {
    msg.content.forEach((block, b) => {
      if (block.type === "tool_use") {
        useLoc.set(block.id, messageBlockTarget(m, b));
      } else if (block.type === "tool_result") {
        resultLoc.set(block.tool_use_id, messageBlockTarget(m, b));
      }
    });
  });
  const pairs = new Map<string, string>();
  for (const [id, useTarget] of useLoc) {
    const resultTarget = resultLoc.get(id);
    if (resultTarget !== undefined) {
      pairs.set(useTarget, resultTarget);
      pairs.set(resultTarget, useTarget);
    }
  }
  return pairs;
}

/**
 * Wrap an `onOverride` so a `message_block_toggle` aimed at a paired
 * tool block also fires the matching twin override. Silent by design:
 * users shouldn't need to think about pair invariants. The twin uses
 * the same `value` as the trigger (`false` to toggle off, `null` to
 * remove the toggle override and re-enable), and a `seen` set guards
 * against duplicates when the caller already includes both halves.
 */
function withPairTandem(
  onOverride: (batch: Override[]) => void,
  pairs: Map<string, string>,
): (batch: Override[]) => void {
  return (batch: Override[]) => {
    const seen = new Set<string>();
    for (const ov of batch) {
      if (ov.kind === "message_block_toggle") seen.add(ov.target);
    }
    const expanded: Override[] = [...batch];
    for (const ov of batch) {
      if (ov.kind !== "message_block_toggle") continue;
      const pairTarget = pairs.get(ov.target);
      if (pairTarget !== undefined && !seen.has(pairTarget)) {
        expanded.push({
          kind: "message_block_toggle",
          target: pairTarget,
          value: ov.value,
        });
        seen.add(pairTarget);
      }
    }
    onOverride(expanded);
  };
}

function MessageCard({
  message,
  msgIdx,
  overrides,
  onOverride,
  readOnly,
}: {
  message: Message;
  msgIdx: number;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  readOnly?: boolean;
}) {
  const tone = SECTION_TONE[message.role];

  const modifiedCount = message.content.filter((_block, blkIdx) => {
    const target = messageBlockTarget(msgIdx, blkIdx);
    const truncateTarget = toolResultBlockTarget(message, blkIdx);
    return (
      overrideValue<string>(overrides, "message_text", target) !== undefined ||
      overrideValue<boolean>(overrides, "message_block_toggle", target) === false ||
      (truncateTarget !== null &&
        overrideValue<string>(overrides, "truncate_tool_result", truncateTarget) !== undefined)
    );
  }).length;

  const keyedBlocks = message.content.map((block, idx) => ({
    block,
    idx,
    key: blockKey(block, idx),
  }));

  // Seeded from the auto-expand pref in the initializer only, so
  // mid-session flips don't retroactively collapse or expand mounted
  // cards. Individual BlockRow clicks still toggle their row.
  const autoExpandBlocks = useUIStore((s) => s.autoExpandBlocks);
  const { toggleAll, toggleOne, isExpanded } = useCollapsibleSet(
    message.content.length,
    !autoExpandBlocks,
  );

  return (
    <div className="card-flush">
      <MasterBar
        label={message.role}
        tone={tone}
        count={message.content.length}
        countUnit="block"
        extras={
          modifiedCount > 0 ? (
            <>
              <span className="h-1 w-1 rounded-full bg-amber" />
              <span className="label text-amber">{modifiedCount} modified</span>
            </>
          ) : undefined
        }
        onToggleAll={toggleAll}
      />
      <div className="hairline-x" />
      <div>
        {keyedBlocks.map((entry, i) => (
          <div key={entry.key}>
            <BlockRow
              block={entry.block}
              msgIdx={msgIdx}
              blkIdx={entry.idx}
              overrides={overrides}
              onOverride={onOverride}
              expanded={isExpanded(entry.idx)}
              onToggleExpanded={() => toggleOne(entry.idx)}
              readOnly={readOnly}
            />
            {i < keyedBlocks.length - 1 && <div className="hairline-x mx-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}

export function MessagesSection({
  messages,
  overrides = [],
  onOverride = noopOverride,
  readOnly,
}: MessagesSectionProps) {
  const messageOverrideCount = overrides.filter(
    (o) =>
      o.kind === "message_text" ||
      o.kind === "message_block_toggle" ||
      o.kind === "truncate_tool_result",
  ).length;

  // Pair-tandem wrapping is an edit-mode invariant: keep tool_use /
  // tool_result halves moving together so the user can't stumble into
  // an orphan. In readOnly the overrides are synthesised from an
  // already-curated payload, so any half-pairing is a historical fact
  // we must render as-is — wrapping here would double-toggle curated
  // overrides into a visibly wrong state.
  const pairMap = useMemo(() => buildPairMap(messages), [messages]);
  const effectiveOnOverride = useMemo(
    () => (readOnly ? onOverride : withPairTandem(onOverride, pairMap)),
    [readOnly, onOverride, pairMap],
  );

  const keyedMessages = messages.map((msg, idx) => ({
    msg,
    idx,
    key: `${msg.role}-${idx}`,
  }));

  const overrideLabel = overrideCountLabel(messageOverrideCount, readOnly);

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Messages &middot; {messages.length}</span>
        {messageOverrideCount > 0 && (
          <span className="chip text-amber ml-2">
            {messageOverrideCount} {overrideLabel}
          </span>
        )}
      </div>
      <div className="space-y-3">
        {keyedMessages.map((entry) => (
          <MessageCard
            key={entry.key}
            message={entry.msg}
            msgIdx={entry.idx}
            overrides={overrides}
            onOverride={effectiveOnOverride}
            readOnly={readOnly}
          />
        ))}
      </div>
    </section>
  );
}
