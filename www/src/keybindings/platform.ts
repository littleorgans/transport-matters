import { DESKTOP_BRIDGE_KEY, type DesktopBridgePlatform, globalWindow } from "../desktopHost";

export type ConcreteModToken = "Meta" | "Control";
export type PlatformSource = "desktop-bridge" | "navigator" | "unknown";

export interface KeybindingPlatform {
  isMac: boolean;
  modToken: ConcreteModToken;
  rawPlatform: string | null;
  source: PlatformSource;
}

export interface PlatformResolutionInput {
  navigator?: Navigator;
  window?: Window;
}

type NavigatorWithUserAgentData = Navigator & {
  userAgentData?: {
    platform?: string;
  };
};

let cachedPlatform: KeybindingPlatform | null = null;

export function getKeybindingPlatform(): KeybindingPlatform {
  cachedPlatform ??= resolveKeybindingPlatform();
  return cachedPlatform;
}

export function resetKeybindingPlatformCache(): void {
  cachedPlatform = null;
}

// Slice 2's registry engine imports this as the public concrete $mod accessor.
export function resolveModToken(
  platform: KeybindingPlatform = getKeybindingPlatform(),
): ConcreteModToken {
  return platform.modToken;
}

export function precompileModTokens(
  tokens: readonly string[],
  platform: KeybindingPlatform = getKeybindingPlatform(),
): string[] {
  return tokens.map((token) => (isModPlaceholder(token) ? platform.modToken : token));
}

export function resolveKeybindingPlatform(input: PlatformResolutionInput = {}): KeybindingPlatform {
  const source = resolveRawPlatform(input);
  const isMac = source.rawPlatform === null ? false : platformLooksMac(source.rawPlatform);
  return {
    isMac,
    modToken: isMac ? "Meta" : "Control",
    rawPlatform: source.rawPlatform,
    source: source.source,
  };
}

function resolveRawPlatform(input: PlatformResolutionInput): {
  rawPlatform: string | null;
  source: PlatformSource;
} {
  const currentWindow = input.window ?? globalWindow();
  const bridge = currentWindow?.[DESKTOP_BRIDGE_KEY];
  if (bridge !== undefined) {
    return {
      rawPlatform: normalizePlatform(bridge.platform),
      source: "desktop-bridge",
    };
  }

  const currentNavigator = input.navigator ?? globalNavigator();
  const navigatorPlatform = platformFromNavigator(currentNavigator);
  if (navigatorPlatform !== null) {
    return {
      rawPlatform: navigatorPlatform,
      source: "navigator",
    };
  }

  return {
    rawPlatform: null,
    source: "unknown",
  };
}

function platformFromNavigator(navigatorSource: Navigator | undefined): string | null {
  if (navigatorSource === undefined) return null;
  const withUserAgentData = navigatorSource as NavigatorWithUserAgentData;
  return (
    normalizePlatform(withUserAgentData.userAgentData?.platform) ||
    normalizePlatform(navigatorSource.userAgent)
  );
}

function platformLooksMac(rawPlatform: string): boolean {
  return /mac|darwin/i.test(rawPlatform);
}

function isModPlaceholder(token: string): boolean {
  return token.trim().toLowerCase() === "$mod";
}

function normalizePlatform(platform: DesktopBridgePlatform | string | undefined): string | null {
  if (platform === undefined) return null;
  const trimmed = platform.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function globalNavigator(): Navigator | undefined {
  return typeof navigator === "undefined" ? undefined : navigator;
}
