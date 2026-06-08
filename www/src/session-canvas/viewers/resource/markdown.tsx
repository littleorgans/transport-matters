import { createElement, Fragment, type ReactNode } from "react";
import { safeHref } from "./primitives/safeHref";

/**
 * Dependency-free markdown renderer for UNTRUSTED transcript content.
 *
 * Security invariant: this NEVER uses React's raw-HTML escape hatch and never
 * builds an HTML string. Every piece of source text reaches the DOM as a React text
 * child, which React escapes. Therefore raw HTML in the source (e.g. a
 * `<script>` or `<img onerror>`) renders as inert, visible text — it can never
 * become live markup. Link hrefs are scheme-checked so `javascript:` URLs are
 * dropped to inert text. The renderer supports a deliberate CommonMark subset
 * (headings, paragraphs, emphasis, inline + fenced code, links, lists, block
 * quotes, hr); anything outside the subset degrades to plain escaped text.
 */
export function renderMarkdown(source: string): ReactNode {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const lineAt = (idx: number): string => lines[idx] ?? "";
  const blocks: ReactNode[] = [];
  const counter = { value: 0 };
  let i = 0;

  while (i < lines.length) {
    const line = lineAt(i);

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    const fence = line.match(/^\s*(`{3,}|~{3,})/);
    if (fence) {
      const marker = (fence[1] ?? "")[0] === "~" ? "~" : "`";
      const closing = new RegExp(`^\\s*${marker === "`" ? "`{3,}" : "~{3,}"}\\s*$`);
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !closing.test(lineAt(i))) {
        body.push(lineAt(i));
        i += 1;
      }
      i += 1; // consume closing fence (if present)
      blocks.push(
        <pre className="canvas-md__pre" key={blockKey(counter)}>
          <code>{body.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = (heading[1] ?? "").length;
      blocks.push(
        createElement(
          `h${level}`,
          { className: `canvas-md__h canvas-md__h${level}`, key: blockKey(counter) },
          renderInline(heading[2] ?? "", counter),
        ),
      );
      i += 1;
      continue;
    }

    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push(<hr className="canvas-md__hr" key={blockKey(counter)} />);
      i += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lineAt(i))) {
        quote.push(lineAt(i).replace(/^\s*>\s?/, ""));
        i += 1;
      }
      blocks.push(
        <blockquote className="canvas-md__quote" key={blockKey(counter)}>
          {renderMarkdown(quote.join("\n"))}
        </blockquote>,
      );
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lineAt(i))) {
        items.push(lineAt(i).replace(/^\s*[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul className="canvas-md__list" key={blockKey(counter)}>
          {items.map((item) => (
            <li className="canvas-md__item" key={blockKey(counter)}>
              {renderInline(item, counter)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lineAt(i))) {
        items.push(lineAt(i).replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol className="canvas-md__list" key={blockKey(counter)}>
          {items.map((item) => (
            <li className="canvas-md__item" key={blockKey(counter)}>
              {renderInline(item, counter)}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    const para: string[] = [];
    while (i < lines.length && lineAt(i).trim() !== "" && !isBlockStart(lineAt(i))) {
      para.push(lineAt(i));
      i += 1;
    }
    blocks.push(
      <p className="canvas-md__p" key={blockKey(counter)}>
        {renderInline(para.join("\n"), counter)}
      </p>,
    );
  }

  return <>{blocks}</>;
}

function isBlockStart(line: string): boolean {
  return (
    /^\s*(`{3,}|~{3,})/.test(line) ||
    /^#{1,6}\s+/.test(line) ||
    /^\s*>\s?/.test(line) ||
    /^\s*[-*+]\s+/.test(line) ||
    /^\s*\d+\.\s+/.test(line) ||
    /^\s*([-*_])(\s*\1){2,}\s*$/.test(line)
  );
}

interface Counter {
  value: number;
}

function blockKey(counter: Counter): string {
  counter.value += 1;
  return `md-${counter.value}`;
}

interface InlineRule {
  re: RegExp;
  make: (match: RegExpExecArray, counter: Counter) => ReactNode;
}

const INLINE_RULES: InlineRule[] = [
  { re: /`([^`]+)`/, make: (m) => <code className="canvas-md__code">{m[1] ?? ""}</code> },
  { re: /\[([^\]]+)\]\(([^)\s]+)\)/, make: (m, c) => renderLink(m[1] ?? "", m[2] ?? "", c) },
  { re: /\*\*([^*]+)\*\*/, make: (m, c) => <strong>{renderInline(m[1] ?? "", c)}</strong> },
  { re: /__([^_]+)__/, make: (m, c) => <strong>{renderInline(m[1] ?? "", c)}</strong> },
  { re: /\*([^*]+)\*/, make: (m, c) => <em>{renderInline(m[1] ?? "", c)}</em> },
  { re: /_([^_]+)_/, make: (m, c) => <em>{renderInline(m[1] ?? "", c)}</em> },
];

/** Tokenize a run of inline markdown into escaped React nodes. */
function renderInline(text: string, counter: Counter): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;

  while (rest.length > 0) {
    let best: { start: number; end: number; node: ReactNode } | null = null;
    for (const rule of INLINE_RULES) {
      const match = rule.re.exec(rest);
      if (match && (best === null || match.index < best.start)) {
        best = {
          start: match.index,
          end: match.index + (match[0] ?? "").length,
          node: rule.make(match, counter),
        };
      }
    }

    if (best === null) {
      out.push(<Fragment key={blockKey(counter)}>{rest}</Fragment>);
      break;
    }
    if (best.start > 0) {
      out.push(<Fragment key={blockKey(counter)}>{rest.slice(0, best.start)}</Fragment>);
    }
    out.push(<Fragment key={blockKey(counter)}>{best.node}</Fragment>);
    rest = rest.slice(best.end);
  }

  return out;
}

function renderLink(label: string, hrefRaw: string, counter: Counter): ReactNode {
  const href = safeHref(hrefRaw);
  const inner = renderInline(label, counter);
  if (href === null) {
    // Unsafe or empty href: render the label as inert text, no anchor.
    return <>{inner}</>;
  }
  return (
    <a className="canvas-md__link" href={href} rel="noopener noreferrer nofollow" target="_blank">
      {inner}
    </a>
  );
}
