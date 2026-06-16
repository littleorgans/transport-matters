import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { fetchExchanges, MAX_ENTRIES } from "../api";
import { exchangesKey } from "../lib/queryKeys";
import type {
  ExchangeTrack,
  ExchangeTrackStub,
  IndexEntry,
  SpawnAnchor,
  TrackRole,
  TrackStatus,
} from "../types";

const EMPTY_TRACK_STUBS: ExchangeTrackStub[] = [];

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

function compareIsoDesc(aTs: string | null | undefined, bTs: string | null | undefined): number {
  if (!aTs || !bTs) return 0;
  const aMs = new Date(aTs).getTime();
  const bMs = new Date(bTs).getTime();
  if (Number.isNaN(aMs) || Number.isNaN(bMs) || aMs === bMs) return 0;
  return bMs - aMs;
}

function compareTs(a: IndexEntry, b: IndexEntry): number {
  return compareIsoDesc(a.ts, b.ts);
}

function adoptAnchor(track: ExchangeTrack, source: SpawnAnchor | null | undefined): void {
  if (source == null) return;
  // Wire rows and pending stubs may arrive in either order. Each non null
  // nested anchor field updates the flat runtime track field so stale nulls
  // never erase known anchor data and later concrete anchors can correct it.
  if (source.track_spawn_exchange_id != null) {
    track.track_spawn_exchange_id = source.track_spawn_exchange_id;
  }
  if (source.track_spawn_tool_use_id != null) {
    track.track_spawn_tool_use_id = source.track_spawn_tool_use_id;
  }
  if (source.track_spawn_order != null) {
    track.track_spawn_order = source.track_spawn_order;
  }
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
      track_spawn_exchange_id: null,
      track_spawn_tool_use_id: null,
      track_spawn_order: null,
      exchanges: [],
      children: [],
    };
    drafts.set(trackId, { track, order: nextOrder });
    nextOrder += 1;
    return track;
  };

  for (const stub of stubs) {
    const track = ensureTrack(
      stub.track_id,
      stub.parent_track_id,
      stub.track_display_name ?? null,
      stub.track_role ?? "subagent",
      stub.status ?? "pending",
    );
    adoptAnchor(track, stub.spawn_anchor);
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
    adoptAnchor(track, entry.spawn_anchor);
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
    const aTs = a.exchanges[0]?.ts;
    const bTs = b.exchanges[0]?.ts;
    const tsOrder = compareIsoDesc(aTs, bTs);
    if (tsOrder !== 0) return tsOrder;
    if (aTs && !bTs) return -1;
    if (!aTs && bTs) return 1;
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
  runId: string | null,
  includeHistory: boolean,
  enabled = true,
  trackStubs: ExchangeTrackStub[] = EMPTY_TRACK_STUBS,
): {
  exchanges: IndexEntry[];
  trackTree: ExchangeTrack[];
  isLoading: boolean;
} {
  const { data: exchanges = [], isLoading } = useQuery({
    queryKey: exchangesKey(runId, includeHistory),
    queryFn: () =>
      fetchExchanges(runId ?? "", MAX_ENTRIES, 0, includeHistory).then((data) =>
        data.slice().reverse().slice(0, MAX_ENTRIES),
      ),
    staleTime: Number.POSITIVE_INFINITY, // SSE keeps data fresh via setQueryData
    enabled: enabled && runId !== null,
  });
  const trackTree = useMemo(
    () => buildExchangeTrackTree(exchanges, trackStubs),
    [exchanges, trackStubs],
  );
  return { exchanges, trackTree, isLoading };
}
