import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement, type KeyboardEvent, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeybindingEngineProvider } from "../../keybindings/engine";
import type { KeybindingPlatform } from "../../keybindings/platform";
import { useCommandCenter } from "./useCommandCenter";

const MAC_PLATFORM: KeybindingPlatform = {
  isMac: true,
  modToken: "Meta",
  rawPlatform: "darwin",
  source: "desktop-bridge",
};

type LauncherKeyEvent = KeyboardEvent<HTMLInputElement> & {
  preventDefault: ReturnType<typeof vi.fn>;
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(KeybindingEngineProvider, { platform: MAC_PLATFORM }, children),
    );
  };
}

function renderCenter() {
  return renderHook(
    () =>
      useCommandCenter({
        onCommand: vi.fn(),
        themeName: "none",
        canvasGestureModifier: "Shift",
      }),
    { wrapper: createWrapper() },
  );
}

function inputKeyEvent(key: string, selectionStart: number): LauncherKeyEvent {
  return {
    key,
    currentTarget: { selectionStart } as HTMLInputElement,
    preventDefault: vi.fn(),
  } as unknown as LauncherKeyEvent;
}

describe("useCommandCenter NavFrame navigation", () => {
  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
  });

  for (const gesture of ["Enter", "ArrowRight"] as const) {
    it(`${gesture} into Settings then ArrowLeft restores the root Settings highlight`, async () => {
      const { result } = renderCenter();

      await waitFor(() => expect(result.current.highlighted).toBe("domain:agents"));

      act(() => {
        result.current.setHighlighted(() => "domain:settings");
      });

      if (gesture === "Enter") {
        act(() => result.current.selectValue("domain:settings"));
      } else {
        const right = inputKeyEvent("ArrowRight", 0);
        act(() => result.current.onInputKeyDown(right));
        expect(right.preventDefault).toHaveBeenCalledTimes(1);
      }

      expect(result.current.scope).toBe("settings");
      expect(result.current.query).toBe("");
      await waitFor(() => expect(result.current.highlighted).toBe("cmd:cycle-theme"));

      const left = inputKeyEvent("ArrowLeft", 0);
      act(() => result.current.onInputKeyDown(left));

      expect(left.preventDefault).toHaveBeenCalledTimes(1);
      expect(result.current.scope).toBe("root");
      expect(result.current.highlighted).toBe("domain:settings");
    });
  }
});
