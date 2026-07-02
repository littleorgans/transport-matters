import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Command, CommandContext, KeybindingPlatform } from "@tm/core/keybindings";
import { createElement, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createKeybindingMap,
  dispatchKeybinding,
  KeybindingEngineProvider,
  selectCommand,
  useFullscreenKeybindings,
} from "./engine";
import { COMMANDS } from "./registry";

const MAC_PLATFORM: KeybindingPlatform = {
  isMac: true,
  modToken: "Meta",
  rawPlatform: "darwin",
  source: "desktop-bridge",
};

const NON_MAC_PLATFORM: KeybindingPlatform = {
  isMac: false,
  modToken: "Control",
  rawPlatform: "linux",
  source: "navigator",
};

function command(id: string): Command {
  const found = COMMANDS.find((candidate) => candidate.id === id);
  if (!found) throw new Error(`missing command ${id}`);
  return found;
}

function context(overrides: Partial<CommandContext> = {}): CommandContext {
  return {
    event: new KeyboardEvent("keydown", { key: "Escape", code: "Escape", cancelable: true }),
    editableTarget: false,
    launcher: null,
    dock: null,
    fullscreen: null,
    ...overrides,
  };
}

function FullscreenProbe({ label, onClose }: { label: string; onClose: (label: string) => void }) {
  const [open, setOpen] = useState(false);
  useFullscreenKeybindings({
    close: () => {
      onClose(label);
      setOpen(false);
    },
    isOpen: () => open,
  });

  return createElement(
    "button",
    { "aria-pressed": open, onClick: () => setOpen(true), type: "button" },
    label,
  );
}

describe("keybinding engine", () => {
  afterEach(() => {
    cleanup();
  });

  it("precompiles $mod before building the tinykeys map", () => {
    const getContext = (event: KeyboardEvent) => context({ event });

    expect(
      Object.keys(
        createKeybindingMap({
          commands: [command("launcher.toggleRoot")],
          platform: MAC_PLATFORM,
          getContext,
        }),
      ),
    ).toEqual(["Meta+K"]);

    expect(
      Object.keys(
        createKeybindingMap({
          commands: [command("launcher.toggleRoot")],
          platform: NON_MAC_PLATFORM,
          getContext,
        }),
      ),
    ).toEqual(["Control+K"]);
  });

  it("gates Agents on palette closed and non editable targets", () => {
    const openScope = vi.fn();
    const agents = command("launcher.openAgents");
    const launcher = {
      toggleRoot: vi.fn(),
      openScope,
      isOpen: () => false,
    };

    dispatchKeybinding([agents], context({ launcher, editableTarget: true }));
    expect(openScope).not.toHaveBeenCalled();

    dispatchKeybinding([agents], context({ launcher, editableTarget: false }));
    expect(openScope).toHaveBeenCalledWith("agents");
  });

  it("keeps Settings active from editable targets", () => {
    const openScope = vi.fn();
    dispatchKeybinding(
      [command("launcher.openSettings")],
      context({
        editableTarget: true,
        launcher: {
          toggleRoot: vi.fn(),
          openScope,
          isOpen: () => true,
        },
      }),
    );

    expect(openScope).toHaveBeenCalledWith("settings");
  });

  it("selects the highest priority matching command for shared bindings", () => {
    const low = { ...command("ui.exitFullscreen"), when: () => true, priority: 1 };
    const high = { ...command("ui.closeDock"), when: () => true, priority: 2 };

    expect(selectCommand([low, high], context())?.id).toBe("ui.closeDock");
  });

  it("orders Escape as dock before fullscreen while palette Escape stands down registry UI commands", () => {
    const closeDock = vi.fn();
    const closeFullscreen = vi.fn();
    const escapeCommands = [command("ui.closeDock"), command("ui.exitFullscreen")];

    dispatchKeybinding(
      escapeCommands,
      context({
        launcher: { toggleRoot: vi.fn(), openScope: vi.fn(), isOpen: () => true },
        dock: { close: closeDock, isOpen: () => true },
        fullscreen: { close: closeFullscreen, isOpen: () => true },
      }),
    );
    expect(closeDock).not.toHaveBeenCalled();
    expect(closeFullscreen).not.toHaveBeenCalled();

    dispatchKeybinding(
      escapeCommands,
      context({
        launcher: { toggleRoot: vi.fn(), openScope: vi.fn(), isOpen: () => false },
        dock: { close: closeDock, isOpen: () => true },
        fullscreen: { close: closeFullscreen, isOpen: () => true },
      }),
    );
    expect(closeDock).toHaveBeenCalledTimes(1);
    expect(closeFullscreen).not.toHaveBeenCalled();

    dispatchKeybinding(
      escapeCommands,
      context({
        launcher: { toggleRoot: vi.fn(), openScope: vi.fn(), isOpen: () => false },
        dock: { close: closeDock, isOpen: () => false },
        fullscreen: { close: closeFullscreen, isOpen: () => true },
      }),
    );
    expect(closeFullscreen).toHaveBeenCalledTimes(1);
  });

  it("closes the open fullscreen target across multiple registrations", () => {
    const close = vi.fn();
    render(
      createElement(
        KeybindingEngineProvider,
        { platform: MAC_PLATFORM },
        createElement(FullscreenProbe, { label: "Second pane", onClose: close }),
        createElement(FullscreenProbe, { label: "First pane", onClose: close }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Second pane" }));
    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });

    expect(close).toHaveBeenCalledTimes(1);
    expect(close).toHaveBeenCalledWith("Second pane");
    expect(screen.getByRole("button", { name: "Second pane" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
