import { getKeybindingPlatform, type KeybindingPlatform, precompileModTokens } from "./platform";

const MODIFIER_ORDER = ["Control", "Alt", "Shift", "Meta"] as const;
type ModifierToken = (typeof MODIFIER_ORDER)[number];

type ModifierBuckets = Record<ModifierToken, boolean>;

const MAC_MODIFIER_LABELS: Record<ModifierToken, string> = {
  Control: "⌃",
  Alt: "⌥",
  Shift: "⇧",
  Meta: "⌘",
};

const WORD_MODIFIER_LABELS: Record<ModifierToken, string> = {
  Control: "Ctrl",
  Alt: "Alt",
  Shift: "Shift",
  Meta: "Meta",
};

export function formatBinding(
  tokens: readonly string[],
  platform: KeybindingPlatform = getKeybindingPlatform(),
): string {
  const { modifiers, keys } = partitionTokens(precompileModTokens(tokens, platform));
  const modifierLabels = MODIFIER_ORDER.filter((token) => modifiers[token]).map((token) =>
    labelModifier(token, platform),
  );
  const keyLabels = keys.map(labelKey);

  if (platform.isMac) {
    return [...modifierLabels, ...keyLabels].join("");
  }
  return [...modifierLabels, ...keyLabels].join("+");
}

function partitionTokens(tokens: readonly string[]): {
  modifiers: ModifierBuckets;
  keys: string[];
} {
  const modifiers: ModifierBuckets = {
    Control: false,
    Alt: false,
    Shift: false,
    Meta: false,
  };
  const keys: string[] = [];

  for (const token of tokens) {
    const modifier = normalizeModifier(token);
    if (modifier === null) {
      keys.push(token);
    } else {
      modifiers[modifier] = true;
    }
  }

  return { modifiers, keys };
}

function normalizeModifier(token: string): ModifierToken | null {
  switch (token.trim().toLowerCase()) {
    case "control":
    case "ctrl":
      return "Control";
    case "alt":
    case "option":
      return "Alt";
    case "shift":
      return "Shift";
    case "meta":
    case "cmd":
    case "command":
      return "Meta";
    default:
      return null;
  }
}

function labelModifier(token: ModifierToken, platform: KeybindingPlatform): string {
  return platform.isMac ? MAC_MODIFIER_LABELS[token] : WORD_MODIFIER_LABELS[token];
}

function labelKey(token: string): string {
  const trimmed = token.trim();
  return trimmed.length === 1 ? trimmed.toUpperCase() : trimmed;
}
