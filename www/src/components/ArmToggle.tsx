interface ArmToggleProps {
  mode: "off" | "armed_once";
  onToggle: () => void;
  error?: boolean;
}

export function ArmToggle({ mode, onToggle, error }: ArmToggleProps) {
  if (error) {
    return (
      <span className="border border-rose/30 bg-rose/5 px-2.5 py-1.5 text-[11px] text-rose uppercase tracking-[0.18em]">
        Breakpoint unavailable
      </span>
    );
  }

  const armed = mode === "armed_once";

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={armed}
      className={`btn group relative flex items-center gap-2.5 px-3.5 py-1.5 text-[12px] font-semibold uppercase tracking-[0.2em] cursor-pointer border transition-colors ${
        armed
          ? "text-sage border-sage/35 bg-sage/8 hover:bg-sage/15 armed-glow"
          : "text-txt-3 border-edge bg-surface hover:text-txt hover:bg-raised"
      }`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full transition-colors ${
          armed ? "bg-sage pulse-dot" : "bg-edge-strong"
        }`}
      />
      <span>{armed ? "Armed" : "Disarmed"}</span>
      <span
        className={`text-[10px] tracking-[0.14em] transition-colors ${
          armed ? "text-sage/55" : "text-txt-3/60"
        }`}
      >
        {armed ? "once" : "idle"}
      </span>
    </button>
  );
}
