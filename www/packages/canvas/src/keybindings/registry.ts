import type { Command, CommandContext } from "@tm/core/keybindings";

const LAUNCHER_PRIORITY = 10;
const DOCK_ESCAPE_PRIORITY = 30;
const FULLSCREEN_ESCAPE_PRIORITY = 20;

function paletteClosed(ctx: CommandContext): boolean {
  return ctx.launcher?.isOpen() !== true;
}

export const COMMANDS: readonly Command[] = [
  {
    id: "launcher.toggleRoot",
    title: "Toggle command center",
    category: "Launcher",
    defaultKeys: ["$mod+K"],
    configurable: false,
    priority: LAUNCHER_PRIORITY,
    when: (ctx) => ctx.launcher !== null,
    run: (ctx) => {
      ctx.event.preventDefault();
      ctx.launcher?.toggleRoot();
    },
  },
  {
    id: "launcher.openAgents",
    title: "Open Agents",
    category: "Launcher",
    defaultKeys: ["$mod+A"],
    configurable: false,
    priority: LAUNCHER_PRIORITY,
    when: (ctx) => ctx.launcher !== null && !ctx.launcher.isOpen() && !ctx.editableTarget,
    run: (ctx) => {
      ctx.event.preventDefault();
      ctx.launcher?.openScope("agents");
    },
  },
  {
    id: "launcher.openSettings",
    title: "Open Settings",
    category: "Launcher",
    defaultKeys: ["$mod+,"],
    configurable: false,
    priority: LAUNCHER_PRIORITY,
    when: (ctx) => ctx.launcher !== null,
    run: (ctx) => {
      ctx.event.preventDefault();
      ctx.launcher?.openScope("settings");
    },
  },
  {
    id: "ui.closeDock",
    title: "Close dock menu",
    category: "UI",
    defaultKeys: ["Escape"],
    configurable: false,
    priority: DOCK_ESCAPE_PRIORITY,
    when: (ctx) => ctx.dock?.isOpen() === true && paletteClosed(ctx),
    run: (ctx) => {
      ctx.dock?.close();
    },
  },
  {
    id: "ui.exitFullscreen",
    title: "Exit fullscreen",
    category: "UI",
    defaultKeys: ["Escape"],
    configurable: false,
    priority: FULLSCREEN_ESCAPE_PRIORITY,
    when: (ctx) =>
      ctx.fullscreen?.isOpen() === true && paletteClosed(ctx) && ctx.dock?.isOpen() !== true,
    run: (ctx) => {
      ctx.fullscreen?.close();
    },
  },
];
