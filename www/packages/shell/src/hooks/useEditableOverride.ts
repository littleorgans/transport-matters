import type { Override, OverrideKind } from "@tm/core/types/overrides";
import { useLayoutEffect, useRef, useState } from "react";
import { hasOverride, overrideValue } from "../lib/overrides";
import { useSyncedLocalValue } from "./useSyncedLocalValue";

interface UseEditableOverrideOptions {
  originalValue: string;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  toggleKind: OverrideKind;
  textKind: OverrideKind;
  target: string;
  initialExpanded?: boolean;
}

export function useEditableOverride({
  originalValue,
  overrides,
  onOverride,
  toggleKind,
  textKind,
  target,
  initialExpanded,
}: UseEditableOverrideOptions) {
  const checked = overrideValue<boolean>(overrides, toggleKind, target) !== false;
  const textOverride = overrideValue<string>(overrides, textKind, target);
  const isModified = textOverride !== undefined;

  const [expanded, setExpanded] = useState(initialExpanded ?? false);
  const [localText, setLocalText] = useSyncedLocalValue(textOverride ?? originalValue);
  const textRef = useRef<HTMLTextAreaElement>(null);

  // Auto-size textarea. useLayoutEffect runs synchronously after DOM
  // commit and before paint, so the textarea hits its correct height
  // on the first frame without a visible resize flash.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-measure on text/expand/checked change
  useLayoutEffect(() => {
    if (textRef.current) {
      textRef.current.style.height = "auto";
      textRef.current.style.height = `${textRef.current.scrollHeight}px`;
    }
  }, [localText, expanded, checked]);

  const handleToggle = () => {
    if (checked) {
      onOverride([{ kind: toggleKind, target, value: false }]);
    } else {
      onOverride([{ kind: toggleKind, target, value: null }]);
    }
  };

  const commitText = () => {
    if (localText === originalValue) {
      onOverride([{ kind: textKind, target, value: null }]);
    } else {
      onOverride([{ kind: textKind, target, value: localText }]);
    }
  };

  const handleReset = () => {
    const batch: Override[] = [];
    if (hasOverride(overrides, toggleKind, target)) {
      batch.push({ kind: toggleKind, target, value: null });
    }
    if (textOverride !== undefined) {
      batch.push({ kind: textKind, target, value: null });
    }
    if (batch.length) onOverride(batch);
  };

  return {
    checked,
    textOverride,
    isModified,
    expanded,
    setExpanded,
    localText,
    setLocalText,
    textRef,
    handleToggle,
    commitText,
    handleReset,
  };
}
