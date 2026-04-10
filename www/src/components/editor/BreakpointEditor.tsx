import { useState } from "react";
import { dropFlow, releaseFlow, releaseFlowUnmodified } from "../../api";
import type { InternalRequest, Message, PausedFlow, SystemPart, ToolDef } from "../../types";
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
  const setSamplingAndModel = (updates: Partial<InternalRequest>) =>
    setEditedIr((ir) => ({ ...ir, ...updates }));

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
      {/* Header with flow info and actions */}
      <PausedHeader
        flowId={pausedFlow.flow_id}
        provider={pausedFlow.ir.provider}
        model={pausedFlow.ir.model}
        pausedAtMs={pausedFlow.paused_at_ms}
      >
        <EditorActions
          originalIr={pausedFlow.ir}
          pipelineAudit={pausedFlow.audit}
          editedIr={editedIr}
          onForward={handleForward}
          onForwardUnmodified={handleForwardUnmodified}
          onDrop={handleDrop}
          loading={loading}
        />
      </PausedHeader>

      <div className="flex flex-1 overflow-hidden">
        {/* Main editing area */}
        <div className="flex-[2] overflow-y-auto px-6 py-5 space-y-6">
          <SamplingSection
            sampling={editedIr.sampling}
            model={editedIr.model}
            onChange={setSamplingAndModel}
          />
          <MessagesSection messages={pausedFlow.ir.messages} onChange={setMessages} />
          <SystemSection parts={pausedFlow.ir.system} onChange={setSystem} />
          <ToolsSection tools={pausedFlow.ir.tools} onChange={setTools} />
        </div>

        {/* Sidebar */}
        <div className="flex-[1] border-l border-edge overflow-y-auto">
          <AuditPanel audit={pausedFlow.audit} />
        </div>
      </div>
    </div>
  );
}
