import type { ReactElement } from "react";

/** Canonical note shown when the server returned only part of a resource. */
export const TRUNCATION_NOTE = "Partial content shown (truncated by the server).";

/**
 * Shared "partial content" note for the resource viewers. The viewers style the
 * note with their own co-located class, so `className` is supplied by the
 * caller; the default wording is owned here so the text/json/markdown viewers
 * cannot drift out of sync. The markdown viewer overrides `message` to say the
 * *source* was truncated.
 */
export function TruncationNote({
  className,
  message = TRUNCATION_NOTE,
}: {
  className: string;
  message?: string;
}): ReactElement {
  return <p className={className}>{message}</p>;
}
