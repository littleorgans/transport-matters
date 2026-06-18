import { Combobox, createListCollection } from "@ark-ui/react/combobox";
import { Portal } from "@ark-ui/react/portal";
import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentRailStyle } from "../../lib/agentPalette";
import {
  buildScopeRows,
  type CommandRow,
  filterRows,
  firstSelectableValue,
  groupRows,
  type LauncherCommand,
  type LauncherScope,
  type RowAction,
  type ScopeRowInputs,
} from "./commandModel";
import { FirstRunHint } from "./FirstRunHint";
import { useLauncherHotkeys } from "./useLauncherHotkeys";
import { useRuntimeTemplates } from "./useRuntimeTemplates";
import "./launcher.css";

export interface CommandCenterProps {
  /** Leaf command dispatcher; the canvas binds these to its store/handlers. */
  onCommand: (command: LauncherCommand) => void;
  /** Current theme name, shown on the Cycle-theme entry's subtitle. */
  themeName: string;
}

const FOOTER_HINTS = "↵ run · → enter · ⌫ back · esc close";

/**
 * The ⌘K command center. Renders zero chrome when closed (only a fading
 * first-run hint); ⌘K/⌘A open it. Built on a single Ark Combobox (this file is
 * the one wrapper that owns its vanilla CSS), with scope state and the row
 * grammar layered on top. Agents fetch lazily and never block a spawn.
 */
export function CommandCenter({ onCommand, themeName }: CommandCenterProps) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<LauncherScope>("root");
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState<string | undefined>(undefined);
  // Sticky: the specialist fleet fetches on the FIRST open and stays cached, so
  // a never-opened palette never hits the endpoint (and never blocks a spawn).
  const [hasOpened, setHasOpened] = useState(false);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const { templates, status, retry } = useRuntimeTemplates(hasOpened);

  const close = useCallback(() => {
    setOpen(false);
    setScope("root");
    setQuery("");
    restoreFocusRef.current?.focus?.();
    restoreFocusRef.current = null;
  }, []);

  const rememberFocus = useCallback(() => {
    const active = document.activeElement;
    restoreFocusRef.current = active instanceof HTMLElement ? active : null;
  }, []);

  const toggleRoot = useCallback(() => {
    setOpen((wasOpen) => {
      if (wasOpen) {
        restoreFocusRef.current?.focus?.();
        restoreFocusRef.current = null;
        return false;
      }
      rememberFocus();
      return true;
    });
    setHasOpened(true);
    setScope("root");
    setQuery("");
  }, [rememberFocus]);

  const openAgents = useCallback(() => {
    rememberFocus();
    setHasOpened(true);
    setScope("agents");
    setQuery("");
    setOpen(true);
  }, [rememberFocus]);

  const isOpenRef = useRef(open);
  isOpenRef.current = open;
  useLauncherHotkeys({ toggleRoot, openAgents, isOpen: () => isOpenRef.current });

  const inputs = useMemo<ScopeRowInputs>(
    () => ({ templates, agentsStatus: status, themeName }),
    [templates, status, themeName],
  );
  const visibleRows = useMemo(
    () => filterRows(buildScopeRows(scope, inputs), query),
    [scope, inputs, query],
  );
  const rowByValue = useMemo(
    () => new Map(visibleRows.map((row) => [row.value, row])),
    [visibleRows],
  );
  const grouped = useMemo(() => groupRows(visibleRows), [visibleRows]);
  const collection = useMemo(
    () =>
      createListCollection({
        items: visibleRows,
        itemToValue: (row) => row.value,
        itemToString: (row) => row.title,
        isItemDisabled: (row) => Boolean(row.disabled),
      }),
    [visibleRows],
  );

  // Keep a valid, selectable row highlighted as the scope/query narrows so ↵ and
  // → always act on something sensible.
  useEffect(() => {
    setHighlighted((current) =>
      current && visibleRows.some((row) => row.value === current && !row.disabled)
        ? current
        : firstSelectableValue(visibleRows),
    );
  }, [visibleRows]);

  const runAction = useCallback(
    (action: RowAction) => {
      if (action.kind === "enter") {
        setScope(action.scope);
        setQuery("");
        return;
      }
      if (action.command.kind === "retry-agents") {
        retry();
        return;
      }
      onCommand(action.command);
      close();
    },
    [onCommand, retry, close],
  );

  const onInputKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
        return;
      }
      const caret = event.currentTarget.selectionStart ?? 0;
      if (event.key === "ArrowRight" && caret >= query.length) {
        const row = highlighted ? rowByValue.get(highlighted) : undefined;
        if (row?.action?.kind === "enter") {
          event.preventDefault();
          runAction(row.action);
        }
        return;
      }
      const popsToRoot =
        event.key === "ArrowLeft" ? caret === 0 : event.key === "Backspace" && query.length === 0;
      if (popsToRoot && scope !== "root") {
        event.preventDefault();
        setScope("root");
      }
    },
    [close, query.length, highlighted, rowByValue, runAction, scope],
  );

  if (!open) return <FirstRunHint />;

  return (
    <div className="launcher" role="presentation">
      {/* Scrim: clicking the dimmed canvas dismisses, like Esc. */}
      <button
        aria-label="Close command center"
        className="launcher__scrim"
        onClick={close}
        type="button"
      />
      <Combobox.Root
        autoFocus
        className="launcher__root"
        closeOnSelect={false}
        collection={collection}
        highlightedValue={highlighted ?? null}
        inputValue={query}
        onHighlightChange={(details) => setHighlighted(details.highlightedValue ?? undefined)}
        onInputValueChange={(details) => setQuery(details.inputValue)}
        onInteractOutside={close}
        onValueChange={(details) => {
          const row = rowByValue.get(details.value[0] ?? "");
          if (row?.action) runAction(row.action);
        }}
        open
        positioning={{ sameWidth: true, gutter: 0, placement: "bottom-start" }}
        selectionBehavior="clear"
        value={[]}
      >
        <Combobox.Control className="launcher__control">
          <span aria-hidden="true" className="launcher__prompt">
            ⌘
          </span>
          <Combobox.Input
            className="launcher__input"
            onKeyDown={onInputKeyDown}
            placeholder={scope === "root" ? "Search agents and commands…" : `Search ${scope}…`}
          />
          <span className="launcher__scope-tag">{scope === "root" ? "" : scope}</span>
        </Combobox.Control>
        <Portal>
          <Combobox.Positioner className="launcher__positioner">
            <Combobox.Content className="launcher__content">
              {grouped.length === 0 ? (
                <p className="launcher__empty">No matches</p>
              ) : (
                grouped.map(([group, rows]) => (
                  <Combobox.ItemGroup className="launcher__group" key={group}>
                    <Combobox.ItemGroupLabel className="launcher__group-label">
                      {group}
                    </Combobox.ItemGroupLabel>
                    {rows.map((row) => (
                      <LauncherRow key={row.value} row={row} />
                    ))}
                  </Combobox.ItemGroup>
                ))
              )}
              <footer className="launcher__footer">
                <span>{FOOTER_HINTS}</span>
                <span className="launcher__brand">TRANSPORT MATTERS</span>
              </footer>
            </Combobox.Content>
          </Combobox.Positioner>
        </Portal>
      </Combobox.Root>
    </div>
  );
}

function LauncherRow({ row }: { row: CommandRow }) {
  const railStyle = row.railSeed ? agentRailStyle(row.railSeed) : undefined;
  return (
    <Combobox.Item className="launcher__row" item={row} style={railStyle}>
      <Combobox.ItemText className="launcher__row-text">
        <span className="launcher__row-title">{row.title}</span>
        {row.subtitle ? <span className="launcher__row-subtitle">{row.subtitle}</span> : null}
      </Combobox.ItemText>
      {row.trailing ? <kbd className="launcher__row-kbd">{row.trailing}</kbd> : null}
    </Combobox.Item>
  );
}
