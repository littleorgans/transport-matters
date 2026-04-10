/**
 * Toggle — the single binary-state control used across the app.
 *
 * Native checkboxes are avoided so the corner policy, focus ring,
 * and colour tokens stay under our control. This is a small square
 * button: empty when off, filled with sage when on, with a 1px
 * inset highlight so it reads as a physical key.
 */

import type { KeyboardEvent } from "react";

interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  size?: "sm" | "md";
  disabled?: boolean;
}

export function Toggle({ checked, onChange, label, size = "md", disabled }: ToggleProps) {
  const dims = size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5";

  const handleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      if (!disabled) onChange(!checked);
    }
  };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      onKeyDown={handleKey}
      className={`${dims} shrink-0 border transition-colors ${
        disabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"
      } ${
        checked ? "bg-sage/80 border-sage/60" : "bg-canvas border-edge-strong hover:border-txt-3"
      }`}
      style={{
        boxShadow: checked
          ? "inset 0 1px 0 0 rgba(255,255,255,0.15), inset 0 -1px 0 0 rgba(0,0,0,0.2)"
          : "inset 0 1px 0 0 rgba(0,0,0,0.4)",
      }}
    />
  );
}
