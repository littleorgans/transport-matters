import { useMemo } from "react";

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
  if (!armed) {
    return <GalaxyArmButton armed={false} onToggle={onToggle} />;
  }

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed
      data-armed="true"
      className="arm-toggle flex items-center justify-start gap-2.5 px-3.5 py-1.5 text-[12px] font-semibold uppercase tracking-[0.2em] cursor-pointer w-[148px] border text-sage border-sage/35 bg-sage/8 hover:bg-sage/15 transition-all duration-[420ms] ease-out"
    >
      <span className="arm-dot inline-block rounded-full bg-sage pulse-dot" />
      <span className="leading-none">Armed</span>
    </button>
  );
}

/* ── Galaxy button — faithful port of Jhey Tompkins' galaxy-button ──
   https://codepen.io/jh3y
   Class names mirror the reference; styles scoped via .galaxy-btn
   so they can't leak. Star vars (angle, duration, delay, alpha,
   size, distance) are randomised once per mount to scatter the
   orbit ring. ── */
function randInt(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1) + min);
}

function makeStar(id: string) {
  return {
    id,
    style: {
      "--angle": `${randInt(0, 360)}deg`,
      "--duration": `${randInt(6, 14)}s`,
      "--delay": `${randInt(0, 14)}s`,
      "--alpha": `${randInt(40, 90) / 100}`,
      "--size": `${randInt(2, 6)}px`,
      "--distance": `${randInt(40, 200)}px`,
    } as React.CSSProperties,
  };
}

function GalaxyArmButton({ armed, onToggle }: { armed: boolean; onToggle: () => void }) {
  const orbitStars = useMemo(() => Array.from({ length: 20 }, (_, i) => makeStar(`os${i}`)), []);

  return (
    <div className="galaxy-button">
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={armed}
        data-armed={armed}
        className="galaxy-btn"
      >
        <span className="spark" />
        <span className="backdrop" />
        <span className="galaxy">
          <span className="galaxy__ring">
            {orbitStars.map((s) => (
              <span key={s.id} className="star" style={s.style} />
            ))}
          </span>
        </span>
        <span className="text">
          <span className="text-rest">{armed ? "Armed" : "Disarmed"}</span>
          <span className="text-hover">{armed ? "Disarm" : "Arm"}</span>
        </span>
      </button>
    </div>
  );
}
