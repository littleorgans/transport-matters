import type { EngineLayoutState, WorldRect } from "../../engine";
import type { CanvasPaneRef, PaneContentRef } from "../model/paneRecords";
import {
  escapeDropLocator,
  resolvePasteHandle,
  type DropLocator,
} from "../viewers/terminal/pasteRegistry";

export const DROP_HINT_MESSAGE = "File drops need the desktop app. URL drags work here.";

export interface CanvasDropDeps {
  resolvePath: ((file: File) => string) | null;
  spawnPane: (ref: PaneContentRef, options?: { focus: boolean }) => string;
  minimizePane: (paneId: string) => void;
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
    return {
      locators: files.map((file) => ({ source: "path", locator: resolvePath(file) })),
      unresolvedFiles: false,
    };
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
  const { panX, panY, scale } = layout.viewport;
  return paneIdAtWorldPoint(layout, {
    x: (point.x - panX) / scale,
    y: (point.y - panY) / scale,
  });
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
    for (const locator of locators) {
      const paneId = deps.spawnPane(refForLocator(locator), { focus: false });
      deps.minimizePane(paneId);
    }
    return;
  }

  for (const locator of locators) {
    deps.spawnPane(refForLocator(locator), undefined);
  }
}

export function deliverPaneDropToTerminal(
  layout: EngineLayoutState,
  contentRef: CanvasPaneRef | undefined,
  movedPaneId: string,
  rect: WorldRect,
): void {
  const locator = locatorForPaneRef(contentRef);
  if (locator === null) return;

  const targetPaneId = paneIdAtWorldPoint(
    layout,
    { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 },
    movedPaneId,
  );
  if (targetPaneId === null) return;

  const paste = resolvePasteHandle(targetPaneId);
  if (paste === null) return;
  paste(escapeDropLocator(locator));
}

function locatorForPaneRef(contentRef: CanvasPaneRef | undefined): DropLocator | null {
  if (contentRef?.kind !== "resource" || !("source" in contentRef)) return null;
  return contentRef.source === "path"
    ? { source: "path", locator: contentRef.path }
    : { source: "url", locator: contentRef.url };
}

function refForLocator(locator: DropLocator): PaneContentRef {
  return locator.source === "path"
    ? { kind: "resource", owner: "local", source: "path", path: locator.locator }
    : { kind: "resource", owner: "local", source: "url", url: locator.locator };
}
