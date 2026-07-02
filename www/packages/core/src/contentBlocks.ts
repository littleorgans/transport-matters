/**
 * Pure content-block derivation helpers shared by the inspector detail views
 * and the canvas transcript/exchange viewers. No React, no store imports —
 * this module is core-bound (P4 of the separation plan).
 */

import { truncatePreview } from "./formatting";
import type { ContentBlock } from "./types/ir";

export function blockSummary(block: ContentBlock, maxPreview = 220): string {
  switch (block.type) {
    case "text": {
      const trimmed = block.text.trim();
      if (trimmed.length === 0) return "(empty)";
      return truncatePreview(trimmed, maxPreview);
    }
    case "tool_use":
      return `${block.name}  ·  ${block.id}`;
    case "tool_result":
      return `→ ${block.tool_use_id.slice(0, 8)}${block.is_error ? "  [error]" : ""}`;
    case "thinking":
      return `${block.text.length.toLocaleString()} chars of reasoning`;
    case "image":
      return "image";
    case "unknown":
      return "unknown block";
  }
}

export function blockKey(block: ContentBlock, idx: number): string {
  switch (block.type) {
    case "tool_use":
      return `tu-${block.id}`;
    case "tool_result":
      return `tr-${block.tool_use_id}`;
    default:
      return `${block.type}-${idx}`;
  }
}
