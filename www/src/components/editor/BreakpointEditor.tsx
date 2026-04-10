import { useState } from "react";
import { dropFlow, releaseFlow, releaseFlowUnmodified } from "../../api";
import type {
  InternalRequest,
  Message,
  PausedFlow,
  SamplingParams,
  SystemPart,
  ToolDef,
} from "../../types";
import { AuditPanel } from "./AuditPanel";
import { EditorActions } from "./EditorActions";
import { MessagesSection } from "./MessagesSection";
import { PausedHeader } from "./PausedHeader";
import { SamplingSection } from "./SamplingSection";
import { SystemSection } from "./SystemSection";
import { ToolsSection } from "./ToolsSection";

interface BreakpointEditorProps {
  pausedFlow: PausedFlow;
  onResolved: () => void;
}

export function BreakpointEditor({ pausedFlow, onResolved }: BreakpointEditorProps) {
  const [editedIr, setEditedIr] = useState<InternalRequest>(() => structuredClone(pausedFlow.ir));
  const [loading, setLoading] = useState(false);

  const setTools = (tools: ToolDef[]) => setEditedIr((ir) => ({ ...ir, tools }));
  const setSystem = (system: SystemPart[]) => setEditedIr((ir) => ({ ...ir, system }));
  const setMessages = (messages: Message[]) => setEditedIr((ir) => ({ ...ir, messages }));
  const setSampling = (sampling: SamplingParams) => setEditedIr((ir) => ({ ...ir, sampling }));

  const handleForward = async () => {
    setLoading(true);
    try {
      await releaseFlow(pausedFlow.flow_id, editedIr);
      onResolved();
    } finally {
      setLoading(false);
    }
  };

  const handleForwardUnmodified = async () => {
    setLoading(true);
    try {
      await releaseFlowUnmodified(pausedFlow.flow_id);
      onResolved();
    } finally {
      setLoading(false);
    }
  };

  const handleDrop = async () => {
    setLoading(true);
    try {
      await dropFlow(pausedFlow.flow_id);
      onResolved();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <PausedHeader flowId={pausedFlow.flow_id} pausedAtMs={pausedFlow.paused_at_ms} />

      <div className="flex flex-1 overflow-hidden">
        {/* Central column: fixed masthead on top, scrollable editor below */}
        <div className="flex flex-[2] flex-col overflow-hidden">
          <EditorActions
            originalIr={pausedFlow.ir}
            pipelineAudit={pausedFlow.audit}
            editedIr={editedIr}
            provider={pausedFlow.ir.provider}
            model={editedIr.model}
            onForward={handleForward}
            onForwardUnmodified={handleForwardUnmodified}
            onDrop={handleDrop}
            loading={loading}
          />

          <div className="flex-1 overflow-y-auto px-8 py-7 space-y-8">
            <SamplingSection sampling={editedIr.sampling} onChange={setSampling} />
            <MessagesSection messages={pausedFlow.ir.messages} onChange={setMessages} />
            <SystemSection parts={pausedFlow.ir.system} onChange={setSystem} />
            <ToolsSection tools={pausedFlow.ir.tools} onChange={setTools} />
            <div className="h-8" />
          </div>
        </div>

        {/* Sidebar */}
        <div className="flex-[1] border-l border-edge overflow-y-auto bg-surface/40">
          <AuditPanel audit={pausedFlow.audit} />
        </div>
      </div>
    </div>
  );
}
