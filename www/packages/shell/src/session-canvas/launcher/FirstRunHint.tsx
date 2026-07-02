import { useEffect, useState } from "react";

const HINT_SEEN_KEY = "tm.launcher.hintSeen";

/**
 * The only resting-state chrome on the zero-chrome canvas: a faint ⌘K hint that
 * fades out on first run and never returns (a seen flag persists in
 * localStorage). Decorative discoverability — the command center itself carries
 * the real screen-reader semantics — so it is aria-hidden.
 */
export function FirstRunHint() {
  const [show, setShow] = useState(() => {
    try {
      return localStorage.getItem(HINT_SEEN_KEY) !== "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (!show) return;
    try {
      localStorage.setItem(HINT_SEEN_KEY, "1");
    } catch {
      // Private mode / blocked storage: the hint still fades, just re-shows next load.
    }
    const timer = window.setTimeout(() => setShow(false), 6500);
    return () => window.clearTimeout(timer);
  }, [show]);

  if (!show) return null;
  return (
    <p aria-hidden="true" className="launcher-hint">
      <kbd className="launcher-hint__kbd">⌘K</kbd>
      <span>to command</span>
    </p>
  );
}
