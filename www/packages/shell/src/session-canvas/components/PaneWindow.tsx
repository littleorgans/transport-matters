import type { PaneRecord } from "../model/paneRecords";
import { PaneChrome } from "./PaneChrome";

export interface PaneWindowProps {
  pane: PaneRecord;
  focused: boolean;
  expanded?: boolean;
  framed?: boolean;
  titleId: string;
  onClose(): void;
  onExpand(): void;
  onFrame(): void;
  onHeaderDoubleClick(event: React.MouseEvent): void;
  onMinimize(): void;
  children: React.ReactNode;
}

// Thin adapter: maps a session-canvas PaneRecord onto the shared content-agnostic PaneChrome.
// No chrome markup lives here anymore (DRY); PaneChrome owns it.
export function PaneWindow({
  pane,
  focused,
  expanded = false,
  framed = false,
  titleId,
  onClose,
  onExpand,
  onFrame,
  onHeaderDoubleClick,
  onMinimize,
  children,
}: PaneWindowProps) {
  return (
    <PaneChrome
      badge={pane.viewerId}
      closeDisabled={pane.contentRef.kind === "session-picker"}
      expanded={expanded}
      focused={focused}
      onClose={onClose}
      onExpand={onExpand}
      onFrame={onFrame}
      onHeaderDoubleClick={onHeaderDoubleClick}
      onMinimize={onMinimize}
      state={framed ? "framed" : pane.chromeState}
      title={pane.title}
      titleId={titleId}
    >
      {children}
    </PaneChrome>
  );
}
