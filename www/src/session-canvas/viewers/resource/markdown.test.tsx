import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderMarkdown, safeHref } from "./markdown";

function renderMd(source: string): HTMLElement {
  return render(<div data-testid="md">{renderMarkdown(source)}</div>).container;
}

describe("renderMarkdown — XSS safety (untrusted transcript content)", () => {
  it("renders a <script> tag in the source as inert text, never a live element", () => {
    const c = renderMd("before <script>window.__pwned = 1</script> after");
    expect(c.querySelector("script")).toBeNull();
    expect(c.textContent).toContain("<script>window.__pwned = 1</script>");
  });

  it("renders an <img onerror> payload as inert text, never an <img>", () => {
    const c = renderMd('<img src=x onerror="window.__pwned=1">');
    expect(c.querySelector("img")).toBeNull();
    expect(c.textContent).toContain("<img src=x onerror=");
  });

  it("drops a javascript: link to inert text — no anchor carries the scheme", () => {
    const c = renderMd("[click me](javascript:alert(1))");
    expect(c.querySelector('a[href^="javascript"]')).toBeNull();
    expect(c.querySelector("a")).toBeNull();
    expect(c.textContent).toContain("click me");
  });

  it("keeps injected markup inert even inside a fenced code block", () => {
    const c = renderMd("```\n<script>alert(1)</script>\n```");
    expect(c.querySelector("script")).toBeNull();
    expect(c.querySelector("pre code")?.textContent).toBe("<script>alert(1)</script>");
  });

  it("never emits onerror/onclick handler attributes from source text", () => {
    const c = renderMd('<div onclick="alert(1)">x</div>');
    expect(c.querySelector("[onclick]")).toBeNull();
    expect(c.querySelector("div[onclick]")).toBeNull();
  });
});

describe("safeHref", () => {
  it("allows http, https, mailto, tel, relative, and anchor links", () => {
    expect(safeHref("https://example.com")).toBe("https://example.com");
    expect(safeHref("http://example.com/a-b")).toBe("http://example.com/a-b");
    expect(safeHref("mailto:a@b.com")).toBe("mailto:a@b.com");
    expect(safeHref("tel:+15551234")).toBe("tel:+15551234");
    expect(safeHref("/local/path")).toBe("/local/path");
    expect(safeHref("#anchor")).toBe("#anchor");
    expect(safeHref("./relative")).toBe("./relative");
  });

  it("blocks dangerous schemes regardless of casing or whitespace", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("  JavaScript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>1</script>")).toBeNull();
    expect(safeHref("vbscript:msgbox(1)")).toBeNull();
    expect(safeHref("file:///etc/passwd")).toBeNull();
    expect(safeHref("")).toBeNull();
  });

  it("rejects hrefs carrying control characters that could smuggle a scheme", () => {
    expect(safeHref("java\tscript:alert(1)")).toBeNull();
    expect(safeHref("java\nscript:alert(1)")).toBeNull();
  });
});

describe("renderMarkdown — subset parsing", () => {
  it("renders headings, emphasis, inline code, and safe links", () => {
    const c = renderMd(
      "## Title\n\nSome **bold** and *italic* and `code` and [site](https://x.io)",
    );
    expect(c.querySelector("h2")?.textContent).toBe("Title");
    expect(c.querySelector("strong")?.textContent).toBe("bold");
    expect(c.querySelector("em")?.textContent).toBe("italic");
    expect(c.querySelector("code")?.textContent).toBe("code");
    const link = c.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://x.io");
    expect(link?.getAttribute("rel")).toContain("noopener");
    expect(link?.getAttribute("target")).toBe("_blank");
  });

  it("renders unordered and ordered lists", () => {
    const c = renderMd("- one\n- two\n\n1. first\n2. second");
    expect(c.querySelectorAll("ul li")).toHaveLength(2);
    expect(c.querySelectorAll("ol li")).toHaveLength(2);
  });

  it("renders blockquotes and horizontal rules", () => {
    const c = renderMd("> quoted line\n\n---");
    expect(c.querySelector("blockquote")?.textContent).toContain("quoted line");
    expect(c.querySelector("hr")).not.toBeNull();
  });
});
