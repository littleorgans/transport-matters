import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { fetchExchanges, MAX_ENTRIES } from "../api";
import type {
  ExchangeTrack,
  ExchangeTrackStub,
  IndexEntry,
  TrackRole,
  TrackStatus,
} from "../types";

interface TrackDraft {
  track: ExchangeTrack;
  order: number;
}

function trackIdForEntry(entry: IndexEntry): string {
  return entry.track_id ?? entry.run_id ?? entry.id;
}

function roleForEntry(entry: IndexEntry, parentTrackId: string | null): TrackRole {
  return entry.track_role ?? (parentTrackId ? "subagent" : "parent");
}

function statusForTrack(exchanges: IndexEntry[], fallback: TrackStatus): TrackStatus {
  if (exchanges.length === 0) return fallback;
  if (exchanges.some((entry) => entry.codex_turn?.status === "open" || entry.res == null)) {
    return "live";
  }
  return fallback === "closed" ? "closed" : "live";
}

function compareTs(a: IndexEntry, b: IndexEntry): number {
  const aTs = new Date(a.ts).getTime();
  const bTs = new Date(b.ts).getTime();
  if (Number.isNaN(aTs) || Number.isNaN(bTs) || aTs === bTs) return 0;
  return aTs - bTs;
}

export function buildExchangeTrackTree(
  exchanges: IndexEntry[],
  stubs: ExchangeTrackStub[] = [],
): ExchangeTrack[] {
  const drafts = new Map<string, TrackDraft>();
  let nextOrder = 0;

  const ensureTrack = (
    trackId: string,
    parentTrackId: string | null,
    displayName: string | null,
    role: TrackRole,
    status: TrackStatus,
  ): ExchangeTrack => {
    const existing = drafts.get(trackId);
    if (existing) {
      existing.track.parent_track_id ??= parentTrackId;
      existing.track.track_display_name ??= displayName;
      existing.track.track_role =
        existing.track.track_role === "parent" ? existing.track.track_role : role;
      if (existing.track.status === "pending" && status !== "pending") {
        existing.track.status = status;
      }
      return existing.track;
    }

    const track: ExchangeTrack = {
      track_id: trackId,
      parent_track_id: parentTrackId,
      track_display_name: displayName,
      track_role: role,
      status,
      exchanges: [],
      children: [],
    };
    drafts.set(trackId, { track, order: nextOrder });
    nextOrder += 1;
    return track;
  };

  for (const stub of stubs) {
    ensureTrack(
      stub.track_id,
      stub.parent_track_id,
      stub.track_display_name ?? null,
      stub.track_role ?? "subagent",
      stub.status ?? "pending",
    );
  }

  for (const entry of exchanges) {
    const trackId = trackIdForEntry(entry);
    const parentTrackId = entry.parent_track_id ?? null;
    const track = ensureTrack(
      trackId,
      parentTrackId,
      entry.track_display_name ?? null,
      roleForEntry(entry, parentTrackId),
      "live",
    );
    track.exchanges.push(entry);
    track.track_display_name = entry.track_display_name ?? track.track_display_name;
    track.status = statusForTrack(track.exchanges, track.status);
  }

  for (const { track } of drafts.values()) {
    track.children = [];
    track.exchanges.sort(compareTs);
  }

  const roots: ExchangeTrack[] = [];
  for (const { track } of drafts.values()) {
    const parent = track.parent_track_id ? drafts.get(track.parent_track_id)?.track : null;
    if (parent && parent.track_id !== track.track_id) {
      parent.children.push(track);
    } else {
      roots.push(track);
    }
  }

  const compareTrack = (a: ExchangeTrack, b: ExchangeTrack) => {
    const aOrder = drafts.get(a.track_id)?.order ?? 0;
    const bOrder = drafts.get(b.track_id)?.order ?? 0;
    return aOrder - bOrder;
  };
  const sortTracks = (tracks: ExchangeTrack[]) => {
    tracks.sort(compareTrack);
    for (const track of tracks) sortTracks(track.children);
  };
  sortTracks(roots);

  return roots;
}

export function useExchanges(
  includeHistory: boolean,
  enabled = true,
): {
  exchanges: IndexEntry[];
  trackTree: ExchangeTrack[];
  isLoading: boolean;
} {
  const { data: exchanges = [], isLoading } = useQuery({
    queryKey: ["exchanges", includeHistory],
    queryFn: () =>
      fetchExchanges(MAX_ENTRIES, 0, includeHistory).then((data) =>
        data.slice().reverse().slice(0, MAX_ENTRIES),
      ),
    staleTime: Number.POSITIVE_INFINITY, // SSE keeps data fresh via setQueryData
    enabled,
  });
  const trackTree = useMemo(() => buildExchangeTrackTree(exchanges), [exchanges]);
  return { exchanges, trackTree, isLoading };
}
