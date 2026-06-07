import type { PaneRecord } from "../model/paneRecords";
import { PaneChrome } from "./PaneChrome";

export interface PaneWindowProps {
  pane: PaneRecord;
  focused: boolean;
  titleId: string;
  onClose(): void;
  children: React.ReactNode;
}

// Thin adapter: maps a session-canvas PaneRecord onto the shared content-agnostic PaneChrome.
// No chrome markup lives here anymore (DRY); PaneChrome owns it.
export function PaneWindow({ pane, focused, titleId, onClose, children }: PaneWindowProps) {
  return (
    <PaneChrome
      badge={pane.viewerId}
      closeDisabled={pane.contentRef.kind === "session-picker"}
      focused={focused}
      onClose={onClose}
      state={pane.chromeState}
      title={pane.title}
      titleId={titleId}
    >
      {children}
    </PaneChrome>
  );
}
