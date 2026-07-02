import { type ReactNode, useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface HoverCardProps {
  /** Content rendered inside the hover card. */
  content: ReactNode;
  /** The element that triggers the hover card. */
  children: ReactNode;
  /** Offset from cursor in pixels. Default: { x: 12, y: 16 } */
  offset?: { x: number; y: number };
}

/**
 * Cursor-following hover card. Shows immediately on mouse enter,
 * tracks the pointer, disappears on mouse leave. Renders via portal
 * to avoid overflow/z-index issues.
 */
export function HoverCard({ content, children, offset = { x: 12, y: 16 } }: HoverCardProps) {
  const [visible, setVisible] = useState(false);
  const posRef = useRef({ x: 0, y: 0 });
  const cardRef = useRef<HTMLDivElement>(null);

  const updatePosition = useCallback(
    (e: React.MouseEvent) => {
      posRef.current = { x: e.clientX + offset.x, y: e.clientY + offset.y };
      if (cardRef.current) {
        const card = cardRef.current;
        const { innerWidth, innerHeight } = window;
        let x = posRef.current.x;
        let y = posRef.current.y;

        // Flip horizontally if overflowing right
        if (x + card.offsetWidth > innerWidth - 8) {
          x = e.clientX - offset.x - card.offsetWidth;
        }
        // Flip vertically if overflowing bottom
        if (y + card.offsetHeight > innerHeight - 8) {
          y = e.clientY - offset.y - card.offsetHeight;
        }

        card.style.left = `${x}px`;
        card.style.top = `${y}px`;
      }
    },
    [offset.x, offset.y],
  );

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: transparent hover-tracking wrapper, not an interactive control
    <div
      onMouseEnter={(e) => {
        updatePosition(e);
        setVisible(true);
      }}
      onMouseMove={updatePosition}
      onMouseLeave={() => setVisible(false)}
      className="contents"
    >
      {children}
      {visible &&
        createPortal(
          <div
            ref={cardRef}
            className="pointer-events-none fixed z-[9999] border border-edge bg-surface px-3 py-2 text-[13px] text-txt shadow-lg"
            style={{ left: posRef.current.x, top: posRef.current.y }}
          >
            {content}
          </div>,
          document.body,
        )}
    </div>
  );
}
