import { describe, expect, it, vi } from "vitest";
import { createKeybindingMap, dispatchKeybinding, selectCommand } from "./engine";
import type { KeybindingPlatform } from "./platform";
import { COMMANDS, type Command, type CommandContext } from "./registry";

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

describe("keybinding engine", () => {
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
});
