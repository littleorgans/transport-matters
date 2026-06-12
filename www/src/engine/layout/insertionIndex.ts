import type { PaneId, WorldRect } from "../types";

export interface OrderedRect {
  paneId: PaneId;
  rect: WorldRect;
}

interface Row {
  startIndex: number;
  rects: OrderedRect[];
  top: number;
  bottom: number;
}

function buildRows(orderedRects: readonly OrderedRect[]): Row[] {
  const rows: Row[] = [];
  for (const [index, entry] of orderedRects.entries()) {
    const current = rows.at(-1);
    // Row-major plans emit a new row when y advances past the previous rect's top.
    if (current === undefined || entry.rect.y > (current.rects.at(-1)?.rect.y ?? 0)) {
      rows.push({
        startIndex: index,
        rects: [entry],
        top: entry.rect.y,
        bottom: entry.rect.y + entry.rect.height,
      });
    } else {
      current.rects.push(entry);
      current.bottom = Math.max(current.bottom, entry.rect.y + entry.rect.height);
    }
  }
  return rows;
}

function rowForPoint(rows: readonly Row[], point: { y: number }): Row {
  let row = rows[0] as Row;
  let best = Number.POSITIVE_INFINITY;
  for (const candidate of rows) {
    const center = (candidate.top + candidate.bottom) / 2;
    const distance = Math.abs(point.y - center);
    if (distance < best) {
      best = distance;
      row = candidate;
    }
  }
  return row;
}

function rowForIndex(rows: readonly Row[], index: number): Row {
  let row = rows[0] as Row;
  for (const candidate of rows) {
    if (index >= candidate.startIndex && index <= candidate.startIndex + candidate.rects.length) {
      row = candidate;
    }
  }
  return row;
}

// Strategy-agnostic insertion point for row-major plans (spec doc 17): the
// row is selected by the point's y against the row bands; within the row,
// before/after is decided on the x axis against the nearest rect center.
// "After the last rect of row N" and "before the first of row N+1" are the
// same index by construction. Empty input returns 0.
export function insertionIndexAtWorldPoint(
  orderedRects: readonly OrderedRect[],
  point: { x: number; y: number },
): number {
  if (orderedRects.length === 0) return 0;

  const row = rowForPoint(buildRows(orderedRects), point);

  for (const [offset, { rect }] of row.rects.entries()) {
    if (point.x < rect.x + rect.width / 2) return row.startIndex + offset;
  }
  return row.startIndex + row.rects.length;
}

export function insertionSlotRect(
  orderedRects: readonly OrderedRect[],
  index: number,
  point: { y: number },
  fallbackRect: WorldRect,
): WorldRect {
  if (orderedRects.length === 0) {
    return { x: fallbackRect.x, y: fallbackRect.y, width: 0, height: fallbackRect.height };
  }

  const rows = buildRows(orderedRects);
  const pointRow = rowForPoint(rows, point);
  const clampedIndex = Math.max(0, Math.min(index, orderedRects.length));
  const inPointRow =
    clampedIndex >= pointRow.startIndex &&
    clampedIndex <= pointRow.startIndex + pointRow.rects.length;
  const row = inPointRow ? pointRow : rowForIndex(rows, clampedIndex);
  const offset = Math.max(0, Math.min(clampedIndex - row.startIndex, row.rects.length));
  const before = row.rects[offset - 1]?.rect;
  const after = row.rects[offset]?.rect;
  const x =
    before && after
      ? (before.x + before.width + after.x) / 2
      : after
        ? after.x
        : before
          ? before.x + before.width
          : fallbackRect.x;
  return { x, y: row.top, width: 0, height: row.bottom - row.top };
}
