import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import {
  messageBlockTarget,
  systemTarget,
  toolResultTarget,
  toolTarget,
} from "../../lib/overrideTargets";
import type {
  CodexDerivedArtifactsDiagnostic,
  CodexDerivedArtifactsState,
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
import { CodexTimeline } from "./CodexTimeline";
import { blockKey, ContentBlockRow } from "./ContentBlocks";
import { ExchangeCard } from "./ExchangeCard";
import {
  detectMessageMutations,
  detectMessageMutationsStructural,
  detectSystemPartMutations,
  detectSystemPartMutationsStructural,
  detectToolMutations,
  detectToolMutationsStructural,
  detectToolResultMutations,
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
  onJumpToTransportFrame?: (messageIndex: number) => void;
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
      batch.push({ kind: "system_part_toggle", target: systemTarget(m.index), value: false });
    } else if (m.curatedText !== undefined) {
      batch.push({ kind: "system_part_text", target: systemTarget(m.index), value: m.curatedText });
    }
  }

  const toolMutations = useAudit
    ? detectToolMutations(audit)
    : structuralDiverges
      ? detectToolMutationsStructural(original, curated)
      : [];
  for (const m of toolMutations) {
    if (m.kind === "disabled") {
      batch.push({ kind: "tool_toggle", target: toolTarget(m.name), value: false });
    } else if (m.curatedDescription !== undefined) {
      batch.push({
        kind: "tool_description",
        target: toolTarget(m.name),
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
    const target = messageBlockTarget(m.msgIdx, m.blkIdx);
    if (m.kind === "disabled") {
      batch.push({ kind: "message_block_toggle", target, value: false });
    } else if (m.curatedText !== undefined) {
      batch.push({ kind: "message_text", target, value: m.curatedText });
    }
  }

  if (useAudit) {
    const toolResultMutations = detectToolResultMutations(audit, original, curated);
    for (const mutation of toolResultMutations) {
      batch.push({
        kind: "truncate_tool_result",
        target: toolResultTarget(mutation.toolUseId),
        value: mutation.curatedText,
      });
    }
  }

  return batch;
}

function diagnosticTone(severity: CodexDerivedArtifactsDiagnostic["severity"]): string {
  if (severity === "error") return "border-rose/30 bg-rose/8 text-rose";
  if (severity === "warning") return "border-amber/30 bg-amber/8 text-amber";
  return "border-sky/30 bg-sky/8 text-sky";
}

function derivedArtifactsTone(status: CodexDerivedArtifactsState["status"]): {
  text: string;
  bg: string;
} {
  if (status === "inconsistent") {
    return { text: "text-rose", bg: "bg-rose/5" };
  }
  if (status === "migration_required") {
    return { text: "text-amber", bg: "bg-amber/5" };
  }
  return { text: "text-sky", bg: "bg-sky/5" };
}

function derivedArtifactsStatusLabel(status: CodexDerivedArtifactsState["status"]): string {
  return status.replaceAll("_", " ");
}

function derivedArtifactsRepairLabel(
  repair: NonNullable<CodexDerivedArtifactsState["repair"]>,
): string {
  const statusBefore = repair.status_before.replaceAll("_", " ");
  return repair.action === "migrated"
    ? `migrated from ${statusBefore}`
    : `repaired from ${statusBefore}`;
}

function CodexDerivedArtifactsCard({
  state,
}: {
  state: CodexDerivedArtifactsState | null | undefined;
}) {
  const repaired = state?.repair?.action != null && state.repair.action !== "none";
  if (
    state == null ||
    state.status === "not_applicable" ||
    (!repaired && (state.status === "supported" || state.diagnostics.length === 0))
  ) {
    return null;
  }

  return (
    <section className="card-flush">
      <div
        className={`flex items-center gap-3 px-4 py-2.5 ${derivedArtifactsTone(state.status).bg}`}
      >
        <span className={`chip ${derivedArtifactsTone(state.status).text}`}>timeline</span>
        <span className="text-[13px] text-txt-3 metric-num">
          {state.diagnostics.length} diagnostic
          {state.diagnostics.length === 1 ? "" : "s"}
        </span>
        <span className="ml-auto chip text-txt-3">
          {state.repair != null && state.repair.action !== "none"
            ? derivedArtifactsRepairLabel(state.repair)
            : derivedArtifactsStatusLabel(state.status)}
        </span>
      </div>
      <div className="hairline-x" />
      <div className="px-4 py-4 space-y-3">
        <p className="text-[13px] font-medium text-txt">
          {state.repair?.action === "migrated"
            ? "Semantic timeline migrated from persisted sidecars and rebuilt from canonical transport during read."
            : repaired
              ? "Semantic timeline rebuilt from canonical transport during read."
              : "Semantic timeline unavailable. Showing backend derived-artifact diagnostics."}
        </p>
        {state.diagnostics.map((diagnostic) => (
          <div
            key={diagnostic.code}
            className={`rounded-md border px-4 py-3 ${diagnosticTone(diagnostic.severity)}`}
          >
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-[0.14em]">{diagnostic.severity}</span>
              <span className="text-[11px] text-txt-3">{diagnostic.code}</span>
            </div>
            <p className="mt-2 text-[13px] font-medium text-txt">{diagnostic.summary}</p>
            {diagnostic.detail && (
              <p className="mt-1 text-[12px] text-txt-2">{diagnostic.detail}</p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export function InspectTab({ detail, onJumpToTransportFrame }: InspectTabProps) {
  const { response_ir } = detail;
  const codexEvents = detail.events;
  const codexTurn = detail.turn;
  const showsCodexTimeline =
    detail.entry.provider === "codex" && codexEvents != null && codexTurn != null;
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

      <CodexDerivedArtifactsCard state={detail.codex_derived_artifacts} />

      {showsCodexTimeline && (
        <CodexTimeline
          events={codexEvents}
          turn={codexTurn}
          onJumpToTransportFrame={onJumpToTransportFrame}
        />
      )}

      {systemParts.length > 0 && (
        <SystemSection parts={systemParts} overrides={syntheticOverrides} readOnly />
      )}

      {requestMessages.length > 0 && (
        <MessagesSection messages={requestMessages} overrides={syntheticOverrides} readOnly />
      )}

      {responseContent.length > 0 && (
        <section>
          <ResponseCard content={responseContent} />
        </section>
      )}

      {tools.length > 0 && <ToolsSection tools={tools} overrides={syntheticOverrides} readOnly />}

      <div className="h-8" />
    </div>
  );
}
