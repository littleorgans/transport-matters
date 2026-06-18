import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, renderHook, waitFor } from "@testing-library/react";
import { createElement, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeybindingEngineProvider } from "../../keybindings/engine";
import type { KeybindingPlatform } from "../../keybindings/platform";
import { installMockTransport, jsonResponse, restoreTransport } from "../testUtils";
import { useCommandCenter } from "./useCommandCenter";

const MAC_PLATFORM: KeybindingPlatform = {
  isMac: true,
  modToken: "Meta",
  rawPlatform: "darwin",
  source: "desktop-bridge",
};

function keyEvent(key: string, selectionStart = 0) {
  return {
    key,
    currentTarget: { selectionStart },
    preventDefault: vi.fn(),
  } as unknown as ReactKeyboardEvent<HTMLInputElement>;
}

function mount(onCommand = vi.fn()) {
  installMockTransport(() => jsonResponse({ items: [] }));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(KeybindingEngineProvider, { platform: MAC_PLATFORM }, children),
    );

  const hook = renderHook(
    () =>
      useCommandCenter({
        onCommand,
        themeName: "Open water",
        canvasGestureModifier: "Shift",
      }),
    { wrapper },
  );
  return { ...hook, onCommand };
}

async function openSettings(result: ReturnType<typeof mount>["result"]) {
  fireEvent.keyDown(window, { key: ",", code: "Comma", metaKey: true });
  await waitFor(() => expect(result.current.open).toBe(true));
  expect(result.current.scope).toBe("settings");
}

async function openRoot(result: ReturnType<typeof mount>["result"]) {
  fireEvent.keyDown(window, { key: "k", code: "KeyK", metaKey: true });
  await waitFor(() => expect(result.current.open).toBe(true));
  expect(result.current.scope).toBe("root");
}

describe("useCommandCenter", () => {
  afterEach(() => {
    cleanup();
    restoreTransport();
    document.body.innerHTML = "";
  });

  it("ArrowRight on Cycle theme runs the command and leaves the launcher open", async () => {
    const { result, onCommand } = mount();
    await openSettings(result);
    await waitFor(() => expect(result.current.highlighted).toBe("cmd:cycle-theme"));

    const event = keyEvent("ArrowRight");
    act(() => result.current.onInputKeyDown(event));

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(onCommand).toHaveBeenCalledWith({ kind: "cycle-theme" });
    expect(result.current.open).toBe(true);
    expect(result.current.scope).toBe("settings");
  });

  it("selecting Cycle theme closes the launcher without running the command", async () => {
    const { result, onCommand } = mount();
    await openSettings(result);

    act(() => result.current.selectValue("cmd:cycle-theme"));

    expect(onCommand).not.toHaveBeenCalled();
    expect(result.current.open).toBe(false);
    expect(result.current.scope).toBe("root");
  });

  it("ArrowRight uses the first selectable row when Ark clears highlight", async () => {
    const { result, onCommand } = mount();
    await openSettings(result);
    act(() => result.current.setHighlighted(undefined));

    const event = keyEvent("ArrowRight");
    act(() => result.current.onInputKeyDown(event));

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(onCommand).toHaveBeenCalledWith({ kind: "cycle-theme" });
    expect(result.current.open).toBe(true);
    expect(result.current.scope).toBe("settings");
  });

  it("ArrowLeft on Cycle theme keeps the existing scope pop behavior", async () => {
    const { result, onCommand } = mount();
    await openSettings(result);
    act(() => result.current.setHighlighted("cmd:cycle-theme"));

    const event = keyEvent("ArrowLeft");
    act(() => result.current.onInputKeyDown(event));

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(onCommand).not.toHaveBeenCalled();
    expect(result.current.open).toBe(true);
    expect(result.current.scope).toBe("root");
  });

  it("ArrowRight on a non cycle row still enters scope", async () => {
    const { result, onCommand } = mount();
    await openRoot(result);
    act(() => result.current.setHighlighted("domain:canvas"));

    const event = keyEvent("ArrowRight");
    act(() => result.current.onInputKeyDown(event));

    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(onCommand).not.toHaveBeenCalled();
    expect(result.current.open).toBe(true);
    expect(result.current.scope).toBe("canvas");
  });
});
