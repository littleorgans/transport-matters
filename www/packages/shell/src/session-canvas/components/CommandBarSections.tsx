import { type ReactNode, useState } from "react";

export interface CommandBarSectionsProps {
  /** Spawn and navigation controls — the default face of the bar. */
  primary: ReactNode;
  /** Secondary controls revealed behind the toggle (e.g. layout tuning). */
  secondary: ReactNode;
  /** Label of the toggle while the primary group is showing. */
  secondaryLabel: string;
  /** Label of the toggle while the secondary group is showing. */
  primaryLabel?: string;
}

/**
 * One command bar, two faces. A single toggle flips between the primary group
 * (spawn/nav buttons that stay on the critical path) and a secondary group
 * (tuning controls that would otherwise crowd the bar). The hidden group is
 * pulled from the accessibility tree, so screen readers only see the live face.
 * Leaves a clean seam for more spawn buttons: append to `primary`.
 */
export function CommandBarSections({
  primary,
  secondary,
  secondaryLabel,
  primaryLabel = "Actions",
}: CommandBarSectionsProps) {
  const [showSecondary, setShowSecondary] = useState(false);
  return (
    <div className="canvas-command-bar__sections">
      <button
        aria-pressed={showSecondary}
        className="canvas-button canvas-command-bar__toggle"
        onClick={() => setShowSecondary((value) => !value)}
        type="button"
      >
        {showSecondary ? primaryLabel : secondaryLabel}
      </button>
      <div className="canvas-command-bar__group" hidden={showSecondary}>
        {primary}
      </div>
      <div
        className="canvas-command-bar__group canvas-command-bar__group--secondary"
        hidden={!showSecondary}
      >
        {secondary}
      </div>
    </div>
  );
}
