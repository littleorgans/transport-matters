import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ExchangeDetail } from "@tm/core/types/exchanges";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InspectTab } from "../components/detail/InspectTab";

const GOOGLE_FONT_HREF =
  "https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,100..800;1,100..800&display=swap";

const EXPORT_COLLAPSE_SCRIPT = `(() => {
  const sections = document.querySelectorAll(".inspect-export-content section");
  for (const section of sections) {
    const header = section.querySelector(".section-rule, .card-flush > :first-child, .card > :first-child");
    if (!(header instanceof HTMLElement)) continue;
    const parent = header.parentElement ?? section;
    const body = Array.from(parent.children).filter((child) => child !== header);
    header.tabIndex = 0;
    header.setAttribute("role", "button");
    const toggle = () => body.forEach((child) => { child.hidden = !child.hidden; });
    header.addEventListener("click", toggle);
    header.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      toggle();
    });
  }
  for (const area of document.querySelectorAll("textarea")) {
    area.style.height = "auto";
    area.style.height = area.scrollHeight + "px";
  }
})();`;

interface BuildExportHtmlArgs {
  contentHtml: string;
  css: string;
  detail: ExchangeDetail;
}

export function serializeInspect(detail: ExchangeDetail): string {
  const queryClient = new QueryClient();
  const tree = createElement(
    QueryClientProvider,
    { client: queryClient },
    createElement(InspectTab, { detail, expandAll: true }),
  );

  return renderToStaticMarkup(tree);
}

export function collectStyles(sourceDocument: Document = document): string {
  const sheets = Array.from(sourceDocument.styleSheets);
  const cssBlocks: string[] = [];

  for (const sheet of sheets) {
    try {
      const rules = Array.from(sheet.cssRules);
      cssBlocks.push(rules.map((rule) => rule.cssText).join("\n"));
    } catch {}
  }

  return cssBlocks.filter((block) => block.length > 0).join("\n");
}

export function buildExportHtml({ contentHtml, css, detail }: BuildExportHtmlArgs): string {
  const title = `Transport Matters Inspect Export: ${detail.entry.provider} ${detail.entry.model}`;
  const rawJson = JSON.stringify(
    {
      request_ir: detail.request_ir,
      request_curated_ir: detail.request_curated_ir,
      response_ir: detail.response_ir,
    },
    null,
    2,
  );

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="${GOOGLE_FONT_HREF}" rel="stylesheet" />
    <title>${escapeHtml(title)}</title>
    <style>
${css}
:root { color-scheme: dark; font-family: "JetBrains Mono", ui-monospace, monospace; }
body { margin: 0; background: var(--color-canvas); color: var(--color-txt); }
.inspect-export-shell { min-height: 100vh; }
.inspect-export-content { max-width: 96rem; margin: 0 auto; }
.inspect-export-raw { max-width: 96rem; margin: 0 auto; padding: 2rem; }
.inspect-export-raw summary { cursor: pointer; }
.inspect-export-raw pre { white-space: pre-wrap; overflow-wrap: anywhere; }
.inspect-export-content textarea { overflow: hidden; }
    </style>
  </head>
  <body>
    <main class="inspect-export-shell bg-canvas text-txt">
      <div class="inspect-export-content">
${contentHtml}
      </div>
      <details class="inspect-export-raw card-flush">
        <summary class="label">Raw JSON</summary>
        <pre>${escapeHtml(rawJson)}</pre>
      </details>
    </main>
    <script>${EXPORT_COLLAPSE_SCRIPT}</script>
  </body>
</html>`;
}

export function downloadInspectHtml(detail: ExchangeDetail): void {
  let html: string;
  try {
    html = buildExportHtml({ contentHtml: serializeInspect(detail), css: collectStyles(), detail });
  } catch (error) {
    console.error("Failed to export Inspect HTML", error);
    return;
  }

  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = buildExportFilename(detail);
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function buildExportFilename(detail: ExchangeDetail): string {
  const parts = [detail.entry.provider, detail.entry.model, detail.entry.id].map(
    sanitizeFilenamePart,
  );
  return `transport-matters-${parts.join("-")}.html`;
}

function sanitizeFilenamePart(value: string): string {
  const cleaned = value
    .trim()
    .replace(/[^a-zA-Z0-9._]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return cleaned.length > 0 ? cleaned : "unknown";
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"]/g, (char) => {
    if (char === "&") return "&amp;";
    if (char === "<") return "&lt;";
    if (char === ">") return "&gt;";
    return "&quot;";
  });
}
