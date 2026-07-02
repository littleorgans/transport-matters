import {
  parseMessageTarget,
  parseSystemIndex,
  parseToolName,
  parseToolResultId,
} from "../../lib/overrideTargets";
import type { ContentBlock, InternalRequest, Message, OverrideAuditEntry } from "../../types";

/**
 * Structured diff between the original request IR and the curated IR the
 * pipeline actually sent upstream. The detail view turns these into
 * synthesized ``Override[]`` so the read-only Inspect tab can reuse the
 * same SystemSection / MessagesSection / ToolsSection the breakpoint
 * editor renders.
 *
 * Primary path is audit-driven: ``pipeline.overrides_applied`` records
 * originals-indexed targets and their applied state, so the client can
 * emit the exact mutation set without having to replay the server's
 * pop-cascade (``_apply_message_block_toggle`` and friends in
 * ``api/src/transport_matters/overrides.py``). That replay is what the old
 * structural differs tried — and got wrong for any row where a toggle
 * dropped a block, because every downstream block shifted left in the
 * curated array and the detector read the shift as a cascade of fake
 * edits.
 *
 * Structural diff remains as a fallback for rows that have no audit but
 * still diverge from the original (e.g. manual edits made in the
 * breakpoint textareas, which are index-safe and never drop blocks).
 * See the April 2026 inspect index shift research memo for
 * the full analysis.
 */
export interface SystemPartMutation {
  index: number;
  kind: "edited" | "deleted";
  /** Present only when ``kind === "edited"`` — the curated text the user/pipeline replaced the original with. */
  curatedText?: string;
}

/**
 * Tool diff. Pairs by ``name`` (which is the editor's target key).
 * ``disabled`` fires when the original name is absent from curated;
 * ``description_edited`` fires when the description text changed and
 * carries the curated description for the synthesized override.
 */
export interface ToolMutation {
  name: string;
  kind: "disabled" | "description_edited";
  /** Present only when ``kind === "description_edited"``. */
  curatedDescription?: string;
}

/**
 * Message-block diff. Targets use the editor's ``msg:${m}:blk:${b}``
 * shape. ``disabled`` fires when the server popped a block via
 * ``message_block_toggle``; ``edited`` fires for text replacements and
 * carries the curated text so the synthesised override can ride with it.
 */
export interface MessageBlockMutation {
  msgIdx: number;
  blkIdx: number;
  kind: "edited" | "disabled";
  /** Present only when ``kind === "edited"``. */
  curatedText?: string;
}

export interface ToolResultMutation {
  toolUseId: string;
  curatedText: string;
}

// ── Audit-driven detectors (primary path) ────────────────────────

type AuditMutationParser<TMutation> = (entry: OverrideAuditEntry) => TMutation | null;

function detectAppliedAuditMutations<TMutation>(
  audit: OverrideAuditEntry[] | undefined,
  parse: AuditMutationParser<TMutation>,
): TMutation[] {
  const mutations: TMutation[] = [];
  if (!audit) return mutations;

  for (const entry of audit) {
    if (!entry.applied) continue;
    const mutation = parse(entry);
    if (mutation !== null) mutations.push(mutation);
  }

  return mutations;
}

export function detectSystemPartMutations(
  audit: OverrideAuditEntry[] | undefined,
): SystemPartMutation[] {
  return detectAppliedAuditMutations<SystemPartMutation>(audit, (entry) => {
    if (entry.kind === "system_part_toggle") {
      const index = parseSystemIndex(entry.target);
      if (index === null) return null;
      // Server applies this kind only when disabling (toggle=true is a
      // noop in ``_apply_system_part_toggle``), so an applied audit
      // entry of this kind unambiguously means the part was dropped.
      return { index, kind: "deleted" };
    }
    if (entry.kind !== "system_part_text" || entry.curated_value === null) return null;
    const index = parseSystemIndex(entry.target);
    return index === null ? null : { index, kind: "edited", curatedText: entry.curated_value };
  });
}

export function detectToolMutations(audit: OverrideAuditEntry[] | undefined): ToolMutation[] {
  return detectAppliedAuditMutations<ToolMutation>(audit, (entry) => {
    if (entry.kind === "tool_toggle") {
      const name = parseToolName(entry.target);
      return name === null ? null : { name, kind: "disabled" };
    }
    if (entry.kind !== "tool_description" || entry.curated_value === null) return null;
    const name = parseToolName(entry.target);
    return name === null
      ? null
      : {
          name,
          kind: "description_edited",
          curatedDescription: entry.curated_value,
        };
  });
}

export function detectMessageMutations(
  audit: OverrideAuditEntry[] | undefined,
): MessageBlockMutation[] {
  return detectAppliedAuditMutations<MessageBlockMutation>(audit, (entry) => {
    const parsed = parseMessageTarget(entry.target);
    if (parsed === null) return null;
    if (entry.kind === "message_block_toggle") {
      // Same as system_part_toggle: applied + disable is the only
      // structurally relevant case (enable is a noop on the server).
      return { msgIdx: parsed.msgIdx, blkIdx: parsed.blkIdx, kind: "disabled" };
    }
    return entry.kind === "message_text" && entry.curated_value !== null
      ? {
          msgIdx: parsed.msgIdx,
          blkIdx: parsed.blkIdx,
          kind: "edited",
          curatedText: entry.curated_value,
        }
      : null;
  });
}

function toolResultText(block: ContentBlock | undefined): string | null {
  if (!block || block.type !== "tool_result") return null;
  return block.content
    .map((contentBlock) => ("text" in contentBlock ? contentBlock.text : ""))
    .join("");
}

function findToolResultText(
  request: InternalRequest | undefined,
  toolUseId: string,
): string | null {
  if (!request) return null;

  for (const message of request.messages ?? []) {
    for (const block of message.content) {
      if (block.type === "tool_result" && block.tool_use_id === toolUseId) {
        return toolResultText(block);
      }
    }
  }

  return null;
}

export function detectToolResultMutations(
  audit: OverrideAuditEntry[] | undefined,
  original: InternalRequest | undefined,
  curated: InternalRequest | undefined,
): ToolResultMutation[] {
  const mutations: ToolResultMutation[] = [];
  if (!audit) return mutations;

  for (const entry of audit) {
    if (!entry.applied || entry.kind !== "truncate_tool_result") {
      continue;
    }
    const toolUseId = parseToolResultId(entry.target);
    if (toolUseId === null) continue;
    if (toolUseId.length === 0) continue;

    const originalText = findToolResultText(original, toolUseId);
    if (originalText === null) continue;

    const curatedText =
      curated !== undefined ? findToolResultText(curated, toolUseId) : entry.curated_value;
    if (curatedText === null || originalText === curatedText) continue;

    mutations.push({ toolUseId, curatedText });
  }

  return mutations;
}

// ── Structural-diff fallback ─────────────────────────────────────
//
// Used when the audit is empty but the curated IR still diverges from
// the original (e.g. a manual edit made in the breakpoint editor's
// textareas). Manual edits go through index-safe IR, so the pop-cascade
// the audit-driven detectors avoid can't bite here.

function blockTextIfText(block: ContentBlock | undefined): string | undefined {
  if (!block) return undefined;
  return block.type === "text" ? block.text : undefined;
}

function disableAllBlocks(msgIdx: number, msg: Message): MessageBlockMutation[] {
  return msg.content.map((_block, blkIdx) => ({
    msgIdx,
    blkIdx,
    kind: "disabled" as const,
  }));
}

export function detectSystemPartMutationsStructural(
  original: InternalRequest | undefined,
  curated: InternalRequest | undefined,
): SystemPartMutation[] {
  const mutations: SystemPartMutation[] = [];
  if (!original || !curated) return mutations;

  const origParts = original.system ?? [];
  const curatedParts = curated.system ?? [];

  // Same-index text change → edited. Indices beyond curated.length fall
  // through to the deletion pass below, so a shortened system list
  // doesn't generate a spurious "edited" for the truncation boundary.
  const paired = Math.min(origParts.length, curatedParts.length);
  for (let i = 0; i < paired; i++) {
    const origText = origParts[i]?.text;
    const curatedText = curatedParts[i]?.text;
    if (origText !== curatedText && curatedText !== undefined) {
      mutations.push({ index: i, kind: "edited", curatedText });
    }
  }

  for (let i = paired; i < origParts.length; i++) {
    mutations.push({ index: i, kind: "deleted" });
  }

  return mutations;
}

export function detectToolMutationsStructural(
  original: InternalRequest | undefined,
  curated: InternalRequest | undefined,
): ToolMutation[] {
  const mutations: ToolMutation[] = [];
  if (!original || !curated) return mutations;

  const origTools = original.tools ?? [];
  const curatedTools = curated.tools ?? [];
  const curatedByName = new Map(curatedTools.map((t) => [t.name, t]));

  for (const tool of origTools) {
    const curatedTool = curatedByName.get(tool.name);
    if (!curatedTool) {
      mutations.push({ name: tool.name, kind: "disabled" });
      continue;
    }
    if (curatedTool.description !== tool.description) {
      mutations.push({
        name: tool.name,
        kind: "description_edited",
        curatedDescription: curatedTool.description,
      });
    }
  }

  return mutations;
}

export function detectMessageMutationsStructural(
  original: InternalRequest | undefined,
  curated: InternalRequest | undefined,
): MessageBlockMutation[] {
  const mutations: MessageBlockMutation[] = [];
  if (!original || !curated) return mutations;

  const origMessages = original.messages ?? [];
  const curatedMessages = curated.messages ?? [];

  for (let msgIdx = 0; msgIdx < origMessages.length; msgIdx++) {
    const origMsg = origMessages[msgIdx];
    if (!origMsg) continue;

    const curatedMsg = curatedMessages[msgIdx];
    if (!curatedMsg) {
      mutations.push(...disableAllBlocks(msgIdx, origMsg));
      continue;
    }

    const origBlocks = origMsg.content ?? [];
    const curatedBlocks = curatedMsg.content ?? [];
    const paired = Math.min(origBlocks.length, curatedBlocks.length);

    for (let blkIdx = 0; blkIdx < paired; blkIdx++) {
      const origText = blockTextIfText(origBlocks[blkIdx]);
      const curatedText = blockTextIfText(curatedBlocks[blkIdx]);
      if (origText !== undefined && curatedText !== undefined && origText !== curatedText) {
        mutations.push({ msgIdx, blkIdx, kind: "edited", curatedText });
      }
    }

    for (let blkIdx = paired; blkIdx < origBlocks.length; blkIdx++) {
      mutations.push({ msgIdx, blkIdx, kind: "disabled" });
    }
  }

  return mutations;
}
