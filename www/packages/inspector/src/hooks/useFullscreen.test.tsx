import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useFullscreen } from "./useFullscreen";

function pressEscape(): void {
  window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
}

describe("useFullscreen", () => {
  it("starts closed and opens on request", () => {
    const { result } = renderHook(() => useFullscreen());
    expect(result.current.isFullscreen).toBe(false);
    act(() => result.current.openFullscreen());
    expect(result.current.isFullscreen).toBe(true);
  });

  it("closes on Escape while open and notifies onClose", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() => useFullscreen({ onClose }));
    act(() => result.current.openFullscreen());
    act(() => pressEscape());
    expect(result.current.isFullscreen).toBe(false);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape while closed", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() => useFullscreen({ onClose }));
    act(() => pressEscape());
    expect(result.current.isFullscreen).toBe(false);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes via closeFullscreen and stops listening after close", () => {
    const onClose = vi.fn();
    const { result } = renderHook(() => useFullscreen({ onClose }));
    act(() => result.current.openFullscreen());
    act(() => result.current.closeFullscreen());
    expect(result.current.isFullscreen).toBe(false);
    expect(onClose).toHaveBeenCalledTimes(1);
    act(() => pressEscape());
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
