/**
 * Allow only safe link schemes; everything else collapses to `null` so the
 * caller can render inert text (or a disabled affordance) instead of a
 * navigable link. Shared by the markdown link renderer and the binary
 * download action so both apply the same scheme allowlist.
 */
export function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (href === "") return null;
  // Control characters (incl. newlines/tabs) can smuggle a scheme past the
  // check, e.g. "java\tscript:". Reject any href that contains one.
  for (let k = 0; k < href.length; k += 1) {
    if (href.charCodeAt(k) < 0x20) return null;
  }
  const scheme = href.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/);
  if (scheme) {
    const allowed = new Set(["http", "https", "mailto", "tel"]);
    if (!allowed.has((scheme[1] ?? "").toLowerCase())) return null;
  }
  return href;
}
