import type { ExchangeTrack, IndexEntry } from "@tm/core/types/exchanges";

export interface OrphanAnchorMeta {
  orphanAnchor: true;
  missingAnchorId: string;
}

export type ExchangeListRow =
  | {
      type: "track";
      key: string;
      track: ExchangeTrack;
      depth: number;
      meta?: OrphanAnchorMeta;
    }
  | {
      type: "exchange";
      key: string;
      entry: IndexEntry;
      depth: number;
      turnSequence: number;
    };

function compareSiblingTracks(a: ExchangeTrack, b: ExchangeTrack): number {
  const aOrder = a.track_spawn_order ?? Number.POSITIVE_INFINITY;
  const bOrder = b.track_spawn_order ?? Number.POSITIVE_INFINITY;
  if (aOrder !== bOrder) return bOrder - aOrder;
  if (a.track_id === b.track_id) return 0;
  return a.track_id < b.track_id ? -1 : 1;
}

function projectTrack(
  track: ExchangeTrack,
  collapsedTrackIds: ReadonlySet<string>,
  depth: number,
  meta?: OrphanAnchorMeta,
): ExchangeListRow[] {
  const rendersHeader = track.track_role === "subagent";
  const rows: ExchangeListRow[] = [];
  if (rendersHeader) {
    rows.push({
      type: "track",
      key: `track:${track.track_id}`,
      track,
      depth,
      meta,
    });
    if (collapsedTrackIds.has(track.track_id)) return rows;
  }

  /*
   * Exchanges indent under a rendered subagent header, but anchored child
   * track headers use the parent track's next depth. This keeps nested inline
   * rows aligned at the spawn point; see the "keeps nested depth tied to the
   * spawning track level" regression case.
   */
  const entryDepth = rendersHeader ? depth + 1 : depth;
  const childDepth = depth + 1;

  const childrenByAnchor = new Map<string, ExchangeTrack[]>();
  const missingAnchorChildren: Array<{ track: ExchangeTrack; meta: OrphanAnchorMeta }> = [];
  const legacyOrphanChildren: ExchangeTrack[] = [];
  const exchangeIds = new Set(track.exchanges.map((entry) => entry.id));

  for (const child of track.children) {
    const anchor = child.track_spawn_exchange_id;
    if (anchor != null && exchangeIds.has(anchor)) {
      const bucket = childrenByAnchor.get(anchor);
      if (bucket) {
        bucket.push(child);
      } else {
        childrenByAnchor.set(anchor, [child]);
      }
    } else if (anchor != null) {
      if (import.meta.env.DEV) {
        console.warn(
          "Transport Matters ExchangeList: subagent anchor outside fetched exchange window",
          {
            trackId: child.track_id,
            missingAnchorId: anchor,
            parentTrackId: track.track_id,
          },
        );
      }
      missingAnchorChildren.push({
        track: child,
        meta: {
          orphanAnchor: true,
          missingAnchorId: anchor,
        },
      });
    } else {
      legacyOrphanChildren.push(child);
    }
  }
  for (const bucket of childrenByAnchor.values()) {
    bucket.sort(compareSiblingTracks);
  }
  missingAnchorChildren.sort((a, b) => compareSiblingTracks(a.track, b.track));
  legacyOrphanChildren.sort(compareSiblingTracks);

  const totalEntries = track.exchanges.length;
  for (const [entryIndex, entry] of track.exchanges.entries()) {
    const anchored = childrenByAnchor.get(entry.id);
    if (anchored) {
      for (const child of anchored) {
        rows.push(...projectTrack(child, collapsedTrackIds, childDepth));
      }
    }
    rows.push({
      type: "exchange",
      key: `exchange:${entry.id}`,
      entry,
      depth: entryDepth,
      turnSequence: totalEntries - entryIndex,
    });
  }

  for (const child of missingAnchorChildren) {
    rows.push(...projectTrack(child.track, collapsedTrackIds, childDepth, child.meta));
  }
  for (const child of legacyOrphanChildren) {
    rows.push(...projectTrack(child, collapsedTrackIds, childDepth));
  }

  return rows;
}

export function projectAnchoredRows(
  tracks: ExchangeTrack[],
  collapsedTrackIds: ReadonlySet<string>,
): ExchangeListRow[] {
  const rows: ExchangeListRow[] = [];
  for (const track of tracks) {
    rows.push(...projectTrack(track, collapsedTrackIds, 0));
  }
  return rows;
}
