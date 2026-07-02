export interface FrameMeterSummary {
  frames: number;
  p95DeltaMs: number;
  maxDeltaMs: number;
}

export class FrameMeter {
  private frameId: number | null = null;
  private lastFrameAt: number | null = null;
  private readonly deltas: number[] = [];

  start(): void {
    this.stop();
    this.lastFrameAt = null;
    this.frameId = requestAnimationFrame(this.recordFrame);
  }

  stop(): FrameMeterSummary {
    if (this.frameId !== null) cancelAnimationFrame(this.frameId);
    this.frameId = null;
    return summarizeFrameDeltas(this.deltas);
  }

  reset(): void {
    this.deltas.length = 0;
    this.lastFrameAt = null;
  }

  private readonly recordFrame = (at: number): void => {
    if (this.lastFrameAt !== null) this.deltas.push(at - this.lastFrameAt);
    this.lastFrameAt = at;
    this.frameId = requestAnimationFrame(this.recordFrame);
  };
}

export function summarizeFrameDeltas(deltas: readonly number[]): FrameMeterSummary {
  if (deltas.length === 0) return { frames: 0, maxDeltaMs: 0, p95DeltaMs: 0 };
  const sorted = [...deltas].sort((a, b) => a - b);
  const p95Index = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return {
    frames: deltas.length,
    maxDeltaMs: sorted[sorted.length - 1] ?? 0,
    p95DeltaMs: sorted[p95Index] ?? 0,
  };
}
