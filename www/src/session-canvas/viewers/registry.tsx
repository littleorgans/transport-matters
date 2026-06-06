import type { PaneContentRef, ViewerProps, ViewerRegistration } from "../model/paneRecords";
import { SessionPickerPane } from "./session-picker/SessionPickerPane";
import { TranscriptChatPane } from "./transcript-chat/TranscriptChatPane";

const registry: ViewerRegistration[] = [
  {
    id: "session-picker",
    title: () => "Session picker",
    canRender: (ref): ref is Extract<PaneContentRef, { kind: "session-picker" }> =>
      ref.kind === "session-picker",
    render: (props) => (
      <SessionPickerPane
        {...(props as ViewerProps<Extract<PaneContentRef, { kind: "session-picker" }>>)}
      />
    ),
  },
  {
    id: "transcript-chat",
    title: (ref) =>
      ref.kind === "session" ? `Transcript ${ref.sessionId.slice(0, 8)}` : "Transcript",
    canRender: (ref): ref is Extract<PaneContentRef, { kind: "session" }> => ref.kind === "session",
    render: (props) => (
      <TranscriptChatPane
        {...(props as ViewerProps<Extract<PaneContentRef, { kind: "session" }>>)}
      />
    ),
  },
];

export function registerViewer(viewer: ViewerRegistration): void {
  const existingIndex = registry.findIndex((entry) => entry.id === viewer.id);
  if (existingIndex >= 0) registry[existingIndex] = viewer;
  else registry.push(viewer);
}

export function resolveViewer(ref: PaneContentRef): ViewerRegistration {
  const viewer = registry.find((entry) => entry.canRender(ref));
  if (!viewer) throw new Error(`No viewer registered for ${ref.kind}.`);
  return viewer;
}
