import type { ReactNode } from "react";

import { TransportMattersIcon } from "../TransportMattersIcon";

type RouteAccent = "amber" | "lavender" | "sky";

const accentClasses: Record<RouteAccent, { dot: string; text: string }> = {
  amber: { dot: "bg-amber", text: "text-amber" },
  lavender: { dot: "bg-lavender", text: "text-lavender" },
  sky: { dot: "bg-sky", text: "text-sky" },
};

interface RouteAtmosphereProps {
  title?: string;
  label?: string;
  body?: ReactNode;
  footer?: ReactNode;
  accent?: RouteAccent;
  fullScreen?: boolean;
  children?: ReactNode;
}

interface ComingSoonRouteProps {
  title: string;
  label: string;
  body: ReactNode;
  accent: RouteAccent;
}

export function RouteBackdrop() {
  return (
    <div
      aria-hidden
      className="absolute inset-0 flex items-center justify-center text-edge-subtle opacity-30 pointer-events-none"
    >
      <TransportMattersIcon className="spin-gentle h-[90vh] w-[90vh]" />
    </div>
  );
}

export function RouteAtmosphere({
  title,
  label,
  body,
  footer,
  accent = "lavender",
  fullScreen = false,
  children,
}: RouteAtmosphereProps) {
  const rootClass = fullScreen
    ? "h-screen bg-canvas text-txt relative overflow-hidden"
    : "relative h-full overflow-hidden";
  const foregroundClass = fullScreen
    ? "absolute inset-0 flex flex-col items-center justify-center gap-6"
    : "absolute inset-0 flex flex-col items-center justify-center gap-7 px-8 text-center";
  const accentClass = accentClasses[accent];

  return (
    <div className={rootClass}>
      <RouteBackdrop />
      <div className={foregroundClass}>
        {children ?? (
          <>
            <div className="flex flex-col items-center gap-4">
              <TransportMattersIcon className="h-[64px] w-[64px] text-txt shrink-0" />
              <h2 className="text-[18px] font-semibold tracking-[0.22em] text-txt uppercase">
                {title}
              </h2>
              <span className="label text-[12px]">{label}</span>
            </div>
            {body ? (
              <p className="max-w-[500px] text-[14px] leading-[1.7] text-txt-3">{body}</p>
            ) : null}
            {footer ? (
              <div
                className={`flex items-center gap-2 text-[12px] uppercase tracking-[0.22em] ${accentClass.text}`}
              >
                <span aria-hidden className={`h-1 w-1 rounded-full ${accentClass.dot}`} />
                <span>{footer}</span>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

export function ComingSoonRoute(props: ComingSoonRouteProps) {
  return <RouteAtmosphere {...props} footer="Coming soon" />;
}
