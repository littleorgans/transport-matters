import { useMemo } from "react";
import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import { overrideValue } from "../../lib/overrides";
import { useUIStore } from "../../stores/uiStore";
import type { Message, Override } from "../../types";
import { MasterBar, SECTION_TONE } from "../detail/atoms";
import { blockKey, ROLE_TONE } from "../detail/ContentBlocks";
import { BlockRow } from "./BlockRow";

interface MessagesSectionProps {
  messages: Message[];
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

function blockTarget(msgIdx: number, blkIdx: number): string {
  return `msg:${msgIdx}:blk:${blkIdx}`;
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
        useLoc.set(block.id, blockTarget(m, b));
      } else if (block.type === "tool_result") {
        resultLoc.set(block.tool_use_id, blockTarget(m, b));
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
}: {
  message: Message;
  msgIdx: number;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}) {
  const tone = SECTION_TONE[message.role] ?? ROLE_TONE[message.role];

  const modifiedCount = message.content.filter((_block, blkIdx) => {
    const target = blockTarget(msgIdx, blkIdx);
    return (
      overrideValue<string>(overrides, "message_text", target) !== undefined ||
      overrideValue<boolean>(overrides, "message_block_toggle", target) === false
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
            />
            {i < keyedBlocks.length - 1 && <div className="hairline-x mx-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}

export function MessagesSection({ messages, overrides, onOverride }: MessagesSectionProps) {
  const messageOverrideCount = overrides.filter(
    (o) => o.kind === "message_text" || o.kind === "message_block_toggle",
  ).length;

  const pairMap = useMemo(() => buildPairMap(messages), [messages]);
  const onOverrideTandem = useMemo(
    () => withPairTandem(onOverride, pairMap),
    [onOverride, pairMap],
  );

  const keyedMessages = messages.map((msg, idx) => ({
    msg,
    idx,
    key: `${msg.role}-${idx}`,
  }));

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Messages &middot; {messages.length}</span>
        {messageOverrideCount > 0 && (
          <span className="chip text-amber ml-2">
            {messageOverrideCount} override{messageOverrideCount !== 1 ? "s" : ""}
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
            onOverride={onOverrideTandem}
          />
        ))}
      </div>
    </section>
  );
}
