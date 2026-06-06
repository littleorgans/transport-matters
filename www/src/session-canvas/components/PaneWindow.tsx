import type { PaneRecord } from "../model/paneRecords";

export interface PaneWindowProps {
  pane: PaneRecord;
  focused: boolean;
  titleId: string;
  onClose(): void;
  children: React.ReactNode;
}

export function PaneWindow({ pane, focused, titleId, onClose, children }: PaneWindowProps) {
  const closeDisabled = pane.contentRef.kind === "session-picker";
  return (
    <article
      aria-label={`${pane.title}, ${pane.viewerId}, ${pane.chromeState}`}
      className="canvas-pane-window"
      data-focused={focused}
      data-state={pane.chromeState}
    >
      <header className="canvas-pane-window__header" data-pane-drag-handle="true">
        <div className="canvas-pane-window__title-wrap">
          <p className="canvas-pane-window__viewer">{pane.viewerId}</p>
          <h2 className="canvas-pane-window__title" id={titleId}>
            {pane.title}
          </h2>
        </div>
        <div className="canvas-pane-window__actions">
          <span className="canvas-pane-window__state">{pane.chromeState}</span>
          <button
            aria-label={`Close ${pane.title}`}
            className="canvas-pane-window__close"
            disabled={closeDisabled}
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>
      </header>
      <div className="canvas-pane-window__body">{children}</div>
      <div
        aria-hidden="true"
        className="canvas-pane-window__resize"
        data-pane-resize-handle="true"
      />
    </article>
  );
}
