import { type KeyboardEvent, type ReactElement, useState } from "react";
import type { ImageContentResponse } from "../../api/resourceContent";

const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.25;

function clampZoom(value: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
}

function resolveSrc(content: ImageContentResponse): string | null {
  if (content.url) {
    return content.url;
  }
  if (content.bytesBase64) {
    return `data:${content.mediaType ?? "image/png"};base64,${content.bytesBase64}`;
  }
  return null;
}

/**
 * Image resource viewer: a zoomable picture stage with button and keyboard
 * controls. Renders only the inner body; the pane frame and provenance label
 * are the orchestrator's concern. Zoom state is conveyed by a text percentage
 * label so it never depends on color alone.
 */
export function ImageResourceViewer({ content }: { content: ImageContentResponse }): ReactElement {
  const [zoom, setZoom] = useState(1);
  const src = resolveSrc(content);

  if (src === null) {
    return <p className="canvas-image__note">No image preview available.</p>;
  }

  const zoomIn = () => setZoom((current) => clampZoom(current + ZOOM_STEP));
  const zoomOut = () => setZoom((current) => clampZoom(current - ZOOM_STEP));
  const reset = () => setZoom(1);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomIn();
    } else if (event.key === "-") {
      event.preventDefault();
      zoomOut();
    } else if (event.key === "0") {
      event.preventDefault();
      reset();
    }
  };

  const percent = `${Math.round(zoom * 100)}%`;

  return (
    <div className="canvas-image">
      <div className="canvas-image__controls">
        <button
          aria-label="Zoom out"
          className="canvas-image__button"
          onClick={zoomOut}
          type="button"
        >
          −
        </button>
        <button
          aria-label="Reset zoom"
          className="canvas-image__button"
          onClick={reset}
          type="button"
        >
          Reset
        </button>
        <button
          aria-label="Zoom in"
          className="canvas-image__button"
          onClick={zoomIn}
          type="button"
        >
          +
        </button>
        <span className="canvas-image__zoom">{percent}</span>
      </div>
      {/* The stage is a native <button>, so it is keyboard-focusable without
          a tabIndex/role and biome's a11y rules pass cleanly. +/-/0 adjust
          the scale; the dedicated controls above remain the primary path. */}
      <button
        aria-label="Image preview, press plus or minus to zoom and zero to reset"
        className="canvas-image__stage"
        onKeyDown={onKeyDown}
        type="button"
      >
        <img
          alt={content.alt ?? content.title}
          className="canvas-image__img"
          src={src}
          style={{ transform: `scale(${zoom})` }}
        />
      </button>
    </div>
  );
}
