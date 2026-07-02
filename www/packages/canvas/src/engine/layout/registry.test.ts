import { describe, expect, it } from "vitest";
import { listLayouts, registerLayout, resolveLayout, validateStrategy } from "./registry";
import type { LayoutStrategy } from "./types";

function makeStrategy(id: string, label = id): LayoutStrategy {
  return {
    id,
    label,
    defaults: { size: 100 },
    controls: [{ kind: "number", key: "size", label: "Size", min: 0, max: 200, step: 10 }],
    plan: ({ paneIds }, params) => ({
      rects: Object.fromEntries(
        paneIds.map((paneId, index) => [
          paneId,
          {
            x: index * Number(params.size),
            y: 0,
            width: Number(params.size),
            height: Number(params.size),
          },
        ]),
      ),
    }),
  };
}

describe("layout registry", () => {
  it("registers and resolves a strategy", () => {
    registerLayout(makeStrategy("reg-test-a"));
    expect(resolveLayout("reg-test-a").id).toBe("reg-test-a");
    expect(listLayouts().some((strategy) => strategy.id === "reg-test-a")).toBe(true);
  });

  it("upserts by id (re-registering replaces, does not duplicate)", () => {
    registerLayout(makeStrategy("reg-test-b", "first"));
    registerLayout(makeStrategy("reg-test-b", "second"));
    expect(resolveLayout("reg-test-b").label).toBe("second");
    expect(listLayouts().filter((strategy) => strategy.id === "reg-test-b")).toHaveLength(1);
  });

  it("throws when resolving an unknown strategy", () => {
    expect(() => resolveLayout("missing-xyz")).toThrow(/No layout strategy/);
  });

  it("rejects a control key that is not in defaults", () => {
    const strategy: LayoutStrategy = {
      ...makeStrategy("bad-key"),
      controls: [{ kind: "number", key: "nope", label: "Nope", min: 0, max: 1, step: 1 }],
    };
    expect(() => validateStrategy(strategy)).toThrow(/not in defaults/);
  });

  it("rejects a control whose kind mismatches the default type", () => {
    const strategy: LayoutStrategy = {
      id: "bad-kind",
      label: "Bad kind",
      defaults: { flag: 5 },
      controls: [{ kind: "toggle", key: "flag", label: "Flag" }],
      plan: () => ({ rects: {} }),
    };
    expect(() => validateStrategy(strategy)).toThrow(/but its default is/);
  });

  it("rejects an enum default that is not in its options", () => {
    const strategy: LayoutStrategy = {
      id: "bad-enum",
      label: "Bad enum",
      defaults: { mode: "z" },
      controls: [
        {
          kind: "enum",
          key: "mode",
          label: "Mode",
          options: [
            { value: "a", label: "A" },
            { value: "b", label: "B" },
          ],
        },
      ],
      plan: () => ({ rects: {} }),
    };
    expect(() => validateStrategy(strategy)).toThrow(/not in options/);
  });
});
