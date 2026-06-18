import { Combobox } from "@ark-ui/react/combobox";
import { Portal } from "@ark-ui/react/portal";
import { useEffect, useRef } from "react";
import { agentRailStyle } from "../../lib/agentPalette";
import { type CommandRow, LAUNCHER_DOMAIN_COUNT, type LauncherCommand } from "./commandModel";
import { FirstRunHint } from "./FirstRunHint";
import { useCommandCenter } from "./useCommandCenter";
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
 * first-run hint); ⌘K/⌘A open it. A thin wrapper over a single Ark Combobox
 * (this file owns its vanilla CSS); all state, hotkeys, the lazy specialist
 * fetch, and the keyboard grammar live in {@link useCommandCenter}.
 */
export function CommandCenter({ onCommand, themeName }: CommandCenterProps) {
  const center = useCommandCenter({ onCommand, themeName });
  const panelRef = useRef<HTMLDivElement>(null);
  // Keep the highlighted row scrolled into the bounded results list as the arrow
  // keys move it (and on auto-highlight). The combobox controls highlight, so we
  // nudge the active option into its scroll container ourselves; block:"nearest"
  // is idempotent, so it never fights Ark's own scrolling.
  useEffect(() => {
    if (!center.highlighted) return;
    panelRef.current
      ?.querySelector<HTMLElement>("[data-part='item'][data-highlighted]")
      ?.scrollIntoView({ block: "nearest" });
  }, [center.highlighted]);

  if (!center.open) return <FirstRunHint />;

  const { scope } = center;
  // Root with an empty query is the domains list; typing flat-searches all
  // domains. The top-right tag and footer hints reflect that mode.
  const showDomains = scope === "root" && center.query.trim().length === 0;
  const scopeTag = showDomains ? `${LAUNCHER_DOMAIN_COUNT} domains` : scope === "root" ? "" : scope;
  const footerHint = showDomains ? "↵ enter scope · esc close" : FOOTER_HINTS;
  return (
    <div className="launcher" role="presentation">
      {/* Scrim: clicking the dimmed canvas dismisses, like Esc. */}
      <button
        aria-label="Close command center"
        className="launcher__scrim"
        onClick={center.close}
        type="button"
      />
      {/* Polite live region for the async specialist fetch (outside the listbox). */}
      <p aria-live="polite" className="launcher__sr-only" role="status">
        {center.fleetStatus}
      </p>
      <Combobox.Root
        autoFocus
        className="launcher__root"
        closeOnSelect={false}
        collection={center.collection}
        highlightedValue={center.highlighted ?? null}
        inputValue={center.query}
        onHighlightChange={(details) =>
          center.setHighlighted(details.highlightedValue ?? undefined)
        }
        onInputValueChange={(details) => center.setQuery(details.inputValue)}
        onInteractOutside={center.close}
        onValueChange={(details) => center.selectValue(details.value[0])}
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
            aria-label="Search agents and commands"
            className="launcher__input"
            onKeyDown={center.onInputKeyDown}
            placeholder={scope === "root" ? "Search agents and commands…" : `Search ${scope}…`}
          />
          <span className="launcher__scope-tag">{scopeTag}</span>
        </Combobox.Control>
        <Portal>
          <Combobox.Positioner className="launcher__positioner">
            {/* Frame wraps the scrolling list + a fixed footer. Combobox.Content
                stays the scroll container so Ark scrolls the active option into
                view; the footer is a sibling OUTSIDE it (no bleed-under). */}
            <div className="launcher__panel" ref={panelRef}>
              <Combobox.Content className="launcher__content">
                {center.grouped.length === 0 ? (
                  <p aria-live="polite" className="launcher__empty" role="status">
                    No matches
                  </p>
                ) : (
                  center.grouped.map(([group, rows]) => (
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
              </Combobox.Content>
              {/* Hints duplicate live key behaviour; hide from the options tree. */}
              <footer aria-hidden="true" className="launcher__footer">
                <span>{footerHint}</span>
                {showDomains ? (
                  <span className="launcher__footer-search">TYPE TO SEARCH ALL</span>
                ) : null}
              </footer>
            </div>
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
