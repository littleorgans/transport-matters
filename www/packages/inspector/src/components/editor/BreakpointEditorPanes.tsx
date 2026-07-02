import type { PausedFlow } from "@tm/core/types/exchanges";
import type { InternalRequest } from "@tm/core/types/ir";
import type { Override } from "@tm/core/types/overrides";
import { JsonView } from "../detail/JsonView";
import type { EditorViewMode } from "./BreakpointEditorTabs";
import { GlobalSection } from "./GlobalSection";
import { MessagesSection } from "./MessagesSection";
import { SamplingSection } from "./SamplingSection";
import { SystemSection } from "./SystemSection";
import { ToolsSection } from "./ToolsSection";

interface BreakpointEditorPanesProps {
  viewMode: EditorViewMode;
  pausedFlow: PausedFlow;
  editedIr: InternalRequest;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

export function BreakpointEditorPanes({
  viewMode,
  pausedFlow,
  editedIr,
  overrides,
  onOverride,
}: BreakpointEditorPanesProps) {
  if (viewMode === "raw") {
    return (
      <div className="flex-1 overflow-y-auto">
        <JsonView payload={editedIr} />
      </div>
    );
  }

  if (viewMode === "messages") {
    return (
      <div className="flex-1 overflow-y-auto px-8 py-7 space-y-8">
        <GlobalSection
          messages={pausedFlow.original_messages ?? pausedFlow.ir.messages}
          overrides={overrides}
          onOverride={onOverride}
        />
        <MessagesSection
          messages={pausedFlow.original_messages ?? pausedFlow.ir.messages}
          overrides={overrides}
          onOverride={onOverride}
        />
        <div className="h-8" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-8 py-7 space-y-8">
      <SamplingSection
        sampling={editedIr.sampling}
        originalSampling={pausedFlow.original_sampling}
        providerExtras={editedIr.provider_extras}
        originalProviderExtras={pausedFlow.original_provider_extras}
        overrides={overrides}
        onOverride={onOverride}
      />
      <SystemSection
        parts={pausedFlow.original_system ?? pausedFlow.ir.system}
        overrides={overrides}
        onOverride={onOverride}
      />
      <ToolsSection
        tools={pausedFlow.original_tools}
        overrides={overrides}
        onOverride={onOverride}
      />
      <div className="h-8" />
    </div>
  );
}
