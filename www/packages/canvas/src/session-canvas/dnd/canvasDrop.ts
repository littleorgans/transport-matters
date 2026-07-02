import type { EngineLayoutState } from "../../engine";
import type { CanvasPaneRef, PaneContentRef } from "../model/paneRecords";
import {
  type DropLocator,
  escapeDropLocator,
  resolvePasteHandle,
} from "../viewers/terminal/pasteRegistry";
import { closestPaneAtWorldPoint, pointerToWorld } from "./dndSpace";
import type { DockDragEntry } from "./dockDragSource";

// The one locator predicate (doc 18): does this ref carry a deliverable
// locator, and which. Shared by the pane-drag delivery path
// (paneDndCallbacks deliveryTargetAt), the dock dragover resolver, and
// handleDockDrop; the null guard lives here, never at the call sites. It sits
// beside its inverse, refForLocator, so the ref<->locator mapping has one home.
export function locatorForPaneRef(ref: CanvasPaneRef | null | undefined): DropLocator | null {
  if (ref == null || ref.kind !== "resource" || !("source" in ref)) return null;
  return ref.source === "path"
    ? { source: "path", locator: ref.path }
    : { source: "url", locator: ref.url };
}

export const DROP_HINT_MESSAGE = "File drops need the desktop app. URL drags work here.";

export interface CanvasDropDeps {
  resolvePath: ((file: File) => string) | null;
  spawnPane: (ref: PaneContentRef, options?: { focus: boolean }) => string;
  // Terminal delivery: the resource goes straight to the dock, never through
  // a spawned pane (which would replan the grid twice in quick succession).
  dockPane: (ref: PaneContentRef) => void;
  showHint: (message: string) => void;
}

export interface DropClassification {
  locators: DropLocator[];
  unresolvedFiles: boolean;
}

export function classifyDrop(
  transfer: DataTransfer,
  resolvePath: ((file: File) => string) | null,
): DropClassification {
  const files = Array.from(transfer.files);
  if (files.length > 0) {
    if (resolvePath === null) return { locators: [], unresolvedFiles: true };
    // Electron returns "" for files with no filesystem backing (e.g. an image
    // dragged out of a browser); an empty locator is not a real path.
    const locators = files
      .map((file) => resolvePath(file))
      .filter((path) => path.length > 0)
      .map((path): DropLocator => ({ source: "path", locator: path }));
    return { locators, unresolvedFiles: locators.length === 0 };
  }

  const uriList = transfer.getData("text/uri-list");
  const locators = uriList
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"))
    .map((line): DropLocator => ({ source: "url", locator: line }));

  return { locators, unresolvedFiles: false };
}

export function paneIdAtWorldPoint(
  layout: EngineLayoutState,
  world: { x: number; y: number },
  excludePaneId?: string,
): string | null {
  let hit: { paneId: string; z: number } | null = null;

  for (const node of Object.values(layout.nodes)) {
    if (node.lifecycle !== "open" || node.paneId === excludePaneId) continue;
    const { x, y, width, height } = node.rect;
    const inside = world.x >= x && world.x <= x + width && world.y >= y && world.y <= y + height;
    if (inside && (hit === null || node.z > hit.z)) hit = { paneId: node.paneId, z: node.z };
  }

  return hit?.paneId ?? null;
}

export function paneIdAtPoint(
  layout: EngineLayoutState,
  point: { x: number; y: number },
): string | null {
  return paneIdAtWorldPoint(layout, pointerToWorld(layout.viewport, point));
}

export function handleCanvasDrop(
  layout: EngineLayoutState,
  point: { x: number; y: number },
  transfer: DataTransfer,
  deps: CanvasDropDeps,
): void {
  const { locators, unresolvedFiles } = classifyDrop(transfer, deps.resolvePath);
  if (unresolvedFiles) {
    deps.showHint(DROP_HINT_MESSAGE);
    return;
  }
  if (locators.length === 0) return;

  const targetPaneId = paneIdAtPoint(layout, point);
  const paste = targetPaneId === null ? null : resolvePasteHandle(targetPaneId);

  if (paste !== null) {
    paste(locators.map(escapeDropLocator).join(" "));
    for (const locator of locators) deps.dockPane(refForLocator(locator));
    return;
  }

  for (const locator of locators) {
    deps.spawnPane(refForLocator(locator), undefined);
  }
}

function refForLocator(locator: DropLocator): PaneContentRef {
  return locator.source === "path"
    ? { kind: "resource", owner: "local", source: "path", path: locator.locator }
    : { kind: "resource", owner: "local", source: "url", url: locator.locator };
}

export interface DockDropDeps {
  // Decision 4 paste branch: a paste is a read, the entry stays docked;
  // dockPane (the runDockPaneFlow seam) de-dupes and bumps it to the front.
  dockPane: (ref: PaneContentRef) => void;
  restorePaneAtIndex: (paneId: string, index: number) => void;
}

// The dock-row drop branch (doc 18), beside handleCanvasDrop: a released dock
// entry either delivers its locator to a paste-handle pane (and stays docked)
// or restores at the order slot the drop point selects. `point` is surface
// relative, the same convention as handleCanvasDrop.
export function handleDockDrop(
  layout: EngineLayoutState,
  point: { x: number; y: number },
  payload: DockDragEntry,
  deps: DockDropDeps,
): void {
  const locator = locatorForPaneRef(payload.ref);
  if (locator !== null) {
    const targetPaneId = paneIdAtPoint(layout, point);
    const paste = targetPaneId === null ? null : resolvePasteHandle(targetPaneId);
    if (paste !== null) {
      paste(escapeDropLocator(locator));
      deps.dockPane(refForLocator(locator));
      return;
    }
  }

  // Restore at the insertion index: the drop TAKES THE TARGET'S SLOT, resolved
  // with the same geometry live pane-drag reorder uses (closestPaneAtWorldPoint),
  // so dock drops and reorders share one targeting feel. Appends on empty canvas.
  const world = pointerToWorld(layout.viewport, point);
  const entries = layout.order.flatMap((paneId) => {
    const node = layout.nodes[paneId];
    return node?.lifecycle === "open" ? [{ id: paneId, rect: node.rect }] : [];
  });
  const hit = closestPaneAtWorldPoint(entries, world);
  const index = hit === null ? layout.order.length : layout.order.indexOf(hit.id);
  deps.restorePaneAtIndex(payload.paneId, index);
}
