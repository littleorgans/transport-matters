import "./pane-window.css";

// Content-agnostic pane chrome shared by PaneWindow (production /canvas) and the lab. Takes
// primitive props only, no PaneRecord, so neither caller duplicates the chrome markup.
// Optional onFrame / onHeaderDoubleClick add framing affordances for callers that wire them.
// Optional `compact` keeps the header to a single line (title + controls) by dropping the kicker
// and the visible state label, the lab opts in so small tiled panes stay legible; production does
// not, so its header is unchanged. The dropped text stays in `data-state` and the aria-label.
// Optional onMinimize adds a [-] button left of Close, so Close stays the rightmost control. Only
// callers with somewhere to minimize to pass it.
export interface PaneChromeProps {
  title: string;
  badge: string;
  state: string;
  titleId: string;
  focused: boolean;
  closeDisabled?: boolean;
  expanded?: boolean;
  compact?: boolean;
  onClose?: () => void;
  onMinimize?: () => void;
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
  compact = false,
  onClose,
  onMinimize,
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
          {compact ? null : <p className="canvas-pane-window__viewer">{badge}</p>}
          <h2 className="canvas-pane-window__title" id={titleId}>
            {title}
          </h2>
        </div>
        {/* The header carries the double-click-to-frame gesture, and these controls live inside it.
            Stop double-clicks on the controls from bubbling up, so a rapid close/minimize (two clicks
            landing on the same button) never registers as a header dblclick that frames the pane as
            it is being removed. Single clicks are unaffected. */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: dblclick guard only; the buttons inside own all real interactions. */}
        <div
          className="canvas-pane-window__actions"
          onDoubleClick={(event) => event.stopPropagation()}
        >
          {compact ? null : <span className="canvas-pane-window__state">{state}</span>}
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
          {onMinimize ? (
            <button
              aria-label={`Minimize ${title}`}
              className="canvas-button"
              onClick={onMinimize}
              type="button"
            >
              {"−"}
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
