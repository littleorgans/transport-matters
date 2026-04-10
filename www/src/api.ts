import type { ExchangeDetail, IndexEntry } from "./types";

export async function fetchExchanges(limit = 50, offset = 0): Promise<IndexEntry[]> {
  const res = await fetch(`/api/exchanges?limit=${limit}&offset=${offset}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch exchanges: ${res.status}`);
  }
  return (await res.json()) as IndexEntry[];
}

export async function fetchExchange(id: string): Promise<ExchangeDetail> {
  const res = await fetch(`/api/exchanges/${encodeURIComponent(id)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch exchange ${id}: ${res.status}`);
  }
  return (await res.json()) as ExchangeDetail;
}
