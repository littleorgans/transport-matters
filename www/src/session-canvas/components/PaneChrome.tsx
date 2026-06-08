// Content-agnostic pane chrome shared by PaneWindow (production /canvas) and the lab. Takes
// primitive props only — no PaneRecord — so neither caller duplicates the chrome markup.
// Optional onFrame / onHeaderDoubleClick add the lab's framing affordances without changing the
// production DOM (PaneWindow passes neither, so no Frame button and no double-click handler).
export interface PaneChromeProps {
  title: string;
  badge: string;
  state: string;
  titleId: string;
  focused: boolean;
  closeDisabled?: boolean;
  expanded?: boolean;
  onClose?: () => void;
  onExpand?: () => void;
  onFrame?: () => void;
  onHeaderDoubleClick?: (event: React.MouseEvent) => void;
  children: React.ReactNode;
}

export function PaneChrome({
  title,
  badge,
  state,
  titleId,
  focused,
  closeDisabled = false,
  expanded = false,
  onClose,
  onExpand,
  onFrame,
  onHeaderDoubleClick,
  children,
}: PaneChromeProps) {
  return (
    <article
      aria-label={`${title}, ${badge}, ${state}`}
      className="canvas-pane-window"
      data-focused={focused}
      data-state={state}
    >
      {/* biome-ignore lint/a11y/noStaticElementInteractions: double-click is a redundant mouse
          convenience for framing; the keyboard-accessible Frame and Close buttons below are the
          real controls. */}
      <header
        className="canvas-pane-window__header"
        data-pane-drag-handle="true"
        onDoubleClick={onHeaderDoubleClick}
      >
        <div className="canvas-pane-window__title-wrap">
          <p className="canvas-pane-window__viewer">{badge}</p>
          <h2 className="canvas-pane-window__title" id={titleId}>
            {title}
          </h2>
        </div>
        <div className="canvas-pane-window__actions">
          <span className="canvas-pane-window__state">{state}</span>
          {onFrame ? (
            <button
              aria-label={`${state === "framed" ? "Unframe" : "Frame"} ${title}`}
              className="canvas-button"
              onClick={onFrame}
              type="button"
            >
              {state === "framed" ? "uF" : "F"}
            </button>
          ) : null}
          {onExpand ? (
            <button
              aria-label={`${expanded ? "Unexpand" : "Expand"} ${title}`}
              className="canvas-button"
              onClick={onExpand}
              type="button"
            >
              {expanded ? "uE" : "E"}
            </button>
          ) : null}
          {onClose ? (
            <button
              aria-label={`Close ${title}`}
              className="canvas-pane-window__close"
              disabled={closeDisabled}
              onClick={onClose}
              type="button"
            >
              Close
            </button>
          ) : null}
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
