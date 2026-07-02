/**
 * True when the event target is a text-editing surface: an input, textarea,
 * select, contenteditable element, or an ARIA textbox. Global keyboard
 * shortcuts consult this so they yield to native editing keys (e.g. ⌘A
 * select-all) while the user is typing, instead of hijacking them.
 */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return target.getAttribute("role") === "textbox";
}

const INTERACTIVE_TARGET_SELECTOR = [
  "a[href]",
  "button",
  "input",
  "select",
  "textarea",
  "[role='button']",
  "[role='checkbox']",
  "[role='combobox']",
  "[role='link']",
  "[role='menuitem']",
  "[role='option']",
  "[role='radio']",
  "[role='slider']",
  "[role='spinbutton']",
  "[role='switch']",
  "[role='tab']",
].join(", ");

export function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest(INTERACTIVE_TARGET_SELECTOR));
}
