import type { PaneId, WorldRect } from "../types";

export interface OrderedRect {
  paneId: PaneId;
  rect: WorldRect;
}

interface Row {
  startIndex: number;
  rects: WorldRect[];
  top: number;
  bottom: number;
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

  const rows: Row[] = [];
  for (const [index, { rect }] of orderedRects.entries()) {
    const current = rows.at(-1);
    // Row-major plans emit a new row when y advances past the previous rect's top.
    if (current === undefined || rect.y > (current.rects.at(-1)?.y ?? 0)) {
      rows.push({ startIndex: index, rects: [rect], top: rect.y, bottom: rect.y + rect.height });
    } else {
      current.rects.push(rect);
      current.bottom = Math.max(current.bottom, rect.y + rect.height);
    }
  }

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

  for (const [offset, rect] of row.rects.entries()) {
    if (point.x < rect.x + rect.width / 2) return row.startIndex + offset;
  }
  return row.startIndex + row.rects.length;
}
