import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import type {
  ContentBlock,
  ExchangeDetail,
  InternalRequest,
  InternalResponse,
  Message,
  Override,
  OverrideAuditEntry,
  SystemPart,
  ToolDef,
} from "../../types";
import { MessagesSection } from "../editor/MessagesSection";
import { SystemSection } from "../editor/SystemSection";
import { ToolsSection } from "../editor/ToolsSection";
import { MasterBar, SECTION_TONE } from "./atoms";
import { blockKey, ContentBlockRow } from "./ContentBlocks";
import { ExchangeCard } from "./ExchangeCard";
import {
  detectMessageMutations,
  detectMessageMutationsStructural,
  detectSystemPartMutations,
  detectSystemPartMutationsStructural,
  detectToolMutations,
  detectToolMutationsStructural,
} from "./mutations";

function ResponseCard({ content }: { content: ContentBlock[] }) {
  const { toggleAll, toggleOne, isExpanded } = useCollapsibleSet(content.length, true);

  return (
    <div className="card-flush">
      <MasterBar
        label="response"
        tone={SECTION_TONE.response}
        count={content.length}
        countUnit="block"
        onToggleAll={toggleAll}
      />
      <div className="hairline-x" />
      <div>
        {content.map((block, idx) => (
          <div key={blockKey(block, idx)}>
            <ContentBlockRow
              block={block}
              expanded={isExpanded(idx)}
              onToggleExpanded={() => toggleOne(idx)}
            />
            {idx < content.length - 1 && <div className="hairline-x mx-4" />}
          </div>
        ))}
      </div>
    </div>
  );
}

interface InspectTabProps {
  detail: ExchangeDetail;
}

/**
 * Synthesize the override list that makes SystemSection / ToolsSection
 * render the curated IR as edits on top of the original. Keeps the
 * detail view on the same data contract as the breakpoint editor so
 * the two surfaces stay visually coherent without a bespoke renderer.
 *
 * Prefers the server-side audit (``pipeline.overrides_applied``): it
 * records originals-indexed targets and their curated text, so there's
 * no need to replay the pop-cascade the server does when block toggles
 * shift later targets. Falls back to structural diff when the audit is
 * empty but the curated IR still diverges — that case is reserved for
 * manual edits made in the breakpoint textareas, which are index-safe.
 */
function buildSyntheticOverrides(
  original: InternalRequest | undefined,
  curated: InternalRequest | undefined,
  audit: OverrideAuditEntry[],
): Override[] {
  const batch: Override[] = [];

  const useAudit = audit.length > 0;
  const structuralDiverges = curated !== undefined && curated !== original;

  const systemMutations = useAudit
    ? detectSystemPartMutations(audit)
    : structuralDiverges
      ? detectSystemPartMutationsStructural(original, curated)
      : [];
  for (const m of systemMutations) {
    if (m.kind === "deleted") {
      batch.push({ kind: "system_part_toggle", target: `system:${m.index}`, value: false });
    } else if (m.curatedText !== undefined) {
      batch.push({ kind: "system_part_text", target: `system:${m.index}`, value: m.curatedText });
    }
  }

  const toolMutations = useAudit
    ? detectToolMutations(audit)
    : structuralDiverges
      ? detectToolMutationsStructural(original, curated)
      : [];
  for (const m of toolMutations) {
    if (m.kind === "disabled") {
      batch.push({ kind: "tool_toggle", target: `tool:${m.name}`, value: false });
    } else if (m.curatedDescription !== undefined) {
      batch.push({
        kind: "tool_description",
        target: `tool:${m.name}`,
        value: m.curatedDescription,
      });
    }
  }

  const messageMutations = useAudit
    ? detectMessageMutations(audit)
    : structuralDiverges
      ? detectMessageMutationsStructural(original, curated)
      : [];
  for (const m of messageMutations) {
    const target = `msg:${m.msgIdx}:blk:${m.blkIdx}`;
    if (m.kind === "disabled") {
      batch.push({ kind: "message_block_toggle", target, value: false });
    } else if (m.curatedText !== undefined) {
      batch.push({ kind: "message_text", target, value: m.curatedText });
    }
  }

  return batch;
}

export function InspectTab({ detail }: InspectTabProps) {
  const { response_ir } = detail;
  const originalRequest = detail.request_ir as unknown as InternalRequest | undefined;
  const curatedRequest = detail.request_curated_ir as unknown as InternalRequest | undefined;

  // Render the ORIGINAL parts/tools so disabled entries still appear;
  // the synthesized overrides drive the greyed-out / edited treatment
  // on top. Falls back to the curated IR when there is no original
  // (e.g. a passthrough row that never paused, where request_ir is the
  // only payload we have).
  const baseRequest = originalRequest ?? curatedRequest;
  const systemParts = (baseRequest?.system ?? []) as SystemPart[];
  const tools = (baseRequest?.tools ?? []) as ToolDef[];
  const requestMessages = (baseRequest?.messages ?? []) as Message[];
  const responseData = response_ir as InternalResponse | null;
  const responseContent = responseData?.content ?? [];

  const audit = detail.request_audit?.entries ?? detail.entry.pipeline?.overrides_applied ?? [];
  const syntheticOverrides = buildSyntheticOverrides(originalRequest, curatedRequest, audit);

  return (
    <div className="px-8 py-7 space-y-10">
      <ExchangeCard detail={detail} />

      {/* System parts */}
      {systemParts.length > 0 && (
        <SystemSection parts={systemParts} overrides={syntheticOverrides} readOnly />
      )}

      {/* Request messages — share the editor's MessagesSection in
          readOnly mode so text edits show the EDIT|DIFF tabs and
          disabled blocks grey out against the original baseline.
          Synthesised overrides carry the curated payload's delta. */}
      {requestMessages.length > 0 && (
        <MessagesSection messages={requestMessages} overrides={syntheticOverrides} readOnly />
      )}

      {/* Response content */}
      {responseContent.length > 0 && (
        <section>
          <ResponseCard content={responseContent} />
        </section>
      )}

      {/* Tools */}
      {tools.length > 0 && <ToolsSection tools={tools} overrides={syntheticOverrides} readOnly />}

      <div className="h-8" />
    </div>
  );
}
