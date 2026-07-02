import type { ContentBlock, Message } from "@tm/core/types/ir";
import type { Override } from "@tm/core/types/overrides";
import { overrideValue } from "../../lib/overrides";
import { messageBlockTarget } from "../../lib/overrideTargets";

/**
 * GLOBAL section. Sweeping toggles that disable or re-enable whole
 * categories of content in the current request in one action.
 *
 * These do NOT persist as a dedicated override kind. Clicking emits a
 * batch of per-block `message_block_toggle` overrides (one per matching
 * block) whose effect carries forward to subsequent requests that
 * replay the same blocks. The checkbox state is derived from "every
 * matching block in the current request is toggled off", so a new
 * request with fresh blocks shows the toggle unchecked again.
 *
 * Tool calls target BOTH `tool_use` and `tool_result` blocks together.
 * The MessagesSection wires up a pair-tandem wrapper to keep the two
 * halves in sync for per-item toggles; GlobalSection runs upstream of
 * that wrapper (it receives the raw `onOverride` from the editor), so
 * it emits both halves explicitly.
 */

interface GlobalSectionProps {
  messages: Message[];
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

function findTargets(messages: Message[], types: readonly ContentBlock["type"][]): string[] {
  const targets: string[] = [];
  messages.forEach((msg, m) => {
    msg.content.forEach((block, b) => {
      if (types.includes(block.type)) targets.push(messageBlockTarget(m, b));
    });
  });
  return targets;
}

function countBlockType(messages: Message[], type: ContentBlock["type"]): number {
  let n = 0;
  for (const msg of messages) {
    for (const block of msg.content) {
      if (block.type === type) n++;
    }
  }
  return n;
}

interface GlobalToggleProps {
  noun: string;
  displayCount: number;
  targets: string[];
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

function GlobalToggle({ noun, displayCount, targets, overrides, onOverride }: GlobalToggleProps) {
  const disabled = targets.length === 0;
  const checked =
    !disabled &&
    targets.every((t) => overrideValue<boolean>(overrides, "message_block_toggle", t) === false);

  const handleClick = () => {
    if (disabled) return;
    const nextValue = checked ? null : false;
    onOverride(
      targets.map((t) => ({
        kind: "message_block_toggle",
        target: t,
        value: nextValue,
      })),
    );
  };

  // Idle label is the stable phrasing the user sees most of the time;
  // active label swaps in the live count so the user knows the size of
  // the action they just armed. The aria-label stays on the idle form
  // so screen-reader users get the same target text in both states.
  const idleLabel = `Strip all ${noun}`;
  const activeLabel = `Strip ${displayCount} ${noun}`;
  const display = checked ? activeLabel : idleLabel;

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={idleLabel}
      onClick={handleClick}
      disabled={disabled}
      className={`flex flex-1 items-center gap-3 px-4 py-3 text-left transition-colors ${
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-raised"
      }`}
    >
      <span
        aria-hidden
        className={`h-3 w-3 shrink-0 border transition-colors ${
          checked ? "bg-sage/80 border-sage/60 key-on" : "bg-canvas border-edge-strong key-off"
        }`}
      />
      <span className="text-[13px] text-txt">{display}</span>
    </button>
  );
}

export function GlobalSection({ messages, overrides, onOverride }: GlobalSectionProps) {
  const thinkingTargets = findTargets(messages, ["thinking"]);
  // tool_use and tool_result must move together so the curated payload
  // never has an orphan half. The provider rejects that.
  const toolTargets = findTargets(messages, ["tool_use", "tool_result"]);
  const thinkingCount = countBlockType(messages, "thinking");
  // One "tool call" == one tool_use block plus its matching tool_result.
  // Displaying the call count (rather than use+result block count) is
  // what matches the user's mental model.
  const toolCallsCount = countBlockType(messages, "tool_use");

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Global</span>
      </div>
      <div className="card-flush flex divide-x divide-edge">
        <GlobalToggle
          noun="thinking blocks"
          displayCount={thinkingCount}
          targets={thinkingTargets}
          overrides={overrides}
          onOverride={onOverride}
        />
        <GlobalToggle
          noun="tool calls"
          displayCount={toolCallsCount}
          targets={toolTargets}
          overrides={overrides}
          onOverride={onOverride}
        />
      </div>
    </section>
  );
}
