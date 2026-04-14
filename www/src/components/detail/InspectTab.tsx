import { useCollapsibleSet } from "../../hooks/useCollapsibleSet";
import type {
  ContentBlock,
  ExchangeDetail,
  InternalResponse,
  Message,
  SystemPart,
} from "../../types";
import { Chevron, MasterBar, SECTION_TONE, SectionRule } from "./atoms";
import { blockKey, ContentBlockRow, countContentBlocks, RequestMessage } from "./ContentBlocks";
import { ExchangeCard } from "./ExchangeCard";
import { groupTools, ToolGroup } from "./ToolGroups";

function SystemPartRow({
  part,
  index,
  expanded,
  onToggleExpanded,
}: {
  part: SystemPart;
  index: number;
  expanded: boolean;
  onToggleExpanded: () => void;
}) {
  const preview = part.text.slice(0, 220) + (part.text.length > 220 ? "\u2026" : "");

  return (
    <div className="px-4 py-2.5">
      <button
        type="button"
        onClick={onToggleExpanded}
        className="flex w-full cursor-pointer items-start gap-3 text-left"
      >
        <span className="chip shrink-0 metric-num">{`[${index}]`}</span>
        {part.cache_hint && <span className="chip shrink-0 text-amber">cached</span>}
        <span className="text-[13px] text-txt-2 truncate leading-5 mt-0.5 flex-1 min-w-0">
          {preview}
        </span>
        <span className="label text-txt-3 metric-num shrink-0 mt-1">
          {part.text.length.toLocaleString()}
        </span>
        <span className="mt-1 shrink-0">
          <Chevron expanded={expanded} />
        </span>
      </button>
      {expanded && (
        <pre className="mt-3 bg-canvas p-4 text-[12px] leading-relaxed text-txt-2 whitespace-pre-wrap border border-edge-subtle block-recess">
          {part.text}
        </pre>
      )}
    </div>
  );
}

function SystemCard({ parts }: { parts: SystemPart[] }) {
  const { allExpanded, toggleAll, toggleOne, isExpanded } = useCollapsibleSet(parts.length, true);

  return (
    <div className="card-flush">
      <MasterBar
        label="system"
        tone={SECTION_TONE.system}
        count={parts.length}
        countUnit="part"
        allExpanded={allExpanded}
        onToggleAll={toggleAll}
      />
      <div className="hairline-x" />
      <div>
        {parts.map((part, idx) => {
          const key = `system-${part.text.slice(0, 40).replace(/\W/g, "")}`;
          return (
            <div key={key}>
              <SystemPartRow
                part={part}
                index={idx}
                expanded={isExpanded(idx)}
                onToggleExpanded={() => toggleOne(idx)}
              />
              {idx < parts.length - 1 && <div className="hairline-x mx-4" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ResponseCard({ content }: { content: ContentBlock[] }) {
  const { allExpanded, toggleAll, toggleOne, isExpanded } = useCollapsibleSet(content.length, true);

  return (
    <div className="card-flush">
      <MasterBar
        label="response"
        tone={SECTION_TONE.response}
        count={content.length}
        countUnit="block"
        allExpanded={allExpanded}
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

export function InspectTab({ detail }: InspectTabProps) {
  const { response_ir } = detail;
  const effectiveRequest = detail.request_curated_ir ?? detail.request_ir;
  const systemParts = (effectiveRequest.system ?? []) as SystemPart[];
  const tools = (effectiveRequest.tools ?? []) as Array<{ name: string }>;
  const toolGroups = groupTools(tools);
  const requestMessages = (effectiveRequest.messages ?? []) as Message[];
  const responseData = response_ir as InternalResponse | null;
  const responseContent = responseData?.content ?? [];

  return (
    <div className="px-8 py-7 space-y-10">
      <ExchangeCard detail={detail} />

      {/* System parts */}
      {systemParts.length > 0 && (
        <section>
          <SystemCard parts={systemParts} />
        </section>
      )}

      {/* Request messages */}
      {requestMessages.length > 0 && (
        <section>
          <SectionRule>Messages &middot; {countContentBlocks(requestMessages)}</SectionRule>
          <div className="space-y-3">
            {requestMessages.map((msg, idx) => {
              const key = `${msg.role}-${idx}-${msg.content.length}`;
              return <RequestMessage key={key} message={msg} />;
            })}
          </div>
        </section>
      )}

      {/* Response content */}
      {responseContent.length > 0 && (
        <section>
          <ResponseCard content={responseContent} />
        </section>
      )}

      {/* Tools */}
      {tools.length > 0 && (
        <section>
          <SectionRule>Tools &middot; {tools.length}</SectionRule>
          <div className="space-y-2">
            {toolGroups.map(([label, items]) => (
              <ToolGroup key={label} label={label} tools={items} />
            ))}
          </div>
        </section>
      )}

      <div className="h-8" />
    </div>
  );
}
