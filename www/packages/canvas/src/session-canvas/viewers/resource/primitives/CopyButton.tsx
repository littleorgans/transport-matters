import { useCallback, useEffect, useRef, useState } from "react";
import "./resource-primitives.css";

/**
 * Copy-to-clipboard control shared by the text, json, and tool-output viewers
 * (the frontend spec's "copy controls"). Deterministic target: the exact `value`
 * passed in. Announces success via an aria-live region and resets after a beat.
 */
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard denied (no permission / insecure context). Stay silent; the
      // content is still selectable by hand.
    }
  }, [value]);

  return (
    <button
      className="canvas-button canvas-resource-copy"
      data-copied={copied ? "true" : undefined}
      onClick={onCopy}
      type="button"
    >
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </button>
  );
}
