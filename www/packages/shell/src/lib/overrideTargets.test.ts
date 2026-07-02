import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  messageBlockTarget,
  parseMessageTarget,
  parseProviderExtrasKey,
  parseSamplingField,
  parseSystemIndex,
  parseToolName,
  parseToolResultId,
  providerExtrasTarget,
  samplingTarget,
  systemTarget,
  toolResultTarget,
  toolTarget,
} from "./overrideTargets";

interface TargetCase<T> {
  target: string;
  value: T | null;
}

interface Fixture {
  builders: {
    tool: Array<{ value: string; target: string }>;
    system: Array<{ index: number; target: string }>;
    tool_result: Array<{ value: string; target: string }>;
    sampling: Array<{ value: string; target: string }>;
    provider_extras: Array<{ value: string; target: string }>;
    message_block: Array<{ msg_idx: number; blk_idx: number; target: string }>;
  };
  parsers: {
    tool: Array<TargetCase<string>>;
    system: Array<TargetCase<number>>;
    tool_result: Array<TargetCase<string>>;
    sampling: Array<TargetCase<string>>;
    provider_extras: Array<TargetCase<string>>;
    message_block: Array<TargetCase<[number, number]>>;
  };
}

function loadFixture(): Fixture {
  const path = resolve(process.cwd(), "../../../shared/override_targets_v1.json");
  return JSON.parse(readFileSync(path, "utf8")) as Fixture;
}

describe("override target grammar", () => {
  it("builds targets from the shared fixture", () => {
    const fixture = loadFixture().builders;

    for (const testCase of fixture.tool) expect(toolTarget(testCase.value)).toBe(testCase.target);
    for (const testCase of fixture.system)
      expect(systemTarget(testCase.index)).toBe(testCase.target);
    for (const testCase of fixture.tool_result)
      expect(toolResultTarget(testCase.value)).toBe(testCase.target);
    for (const testCase of fixture.sampling)
      expect(samplingTarget(testCase.value)).toBe(testCase.target);
    for (const testCase of fixture.provider_extras)
      expect(providerExtrasTarget(testCase.value)).toBe(testCase.target);
    for (const testCase of fixture.message_block)
      expect(messageBlockTarget(testCase.msg_idx, testCase.blk_idx)).toBe(testCase.target);
  });

  it("parses targets from the shared fixture", () => {
    const fixture = loadFixture().parsers;

    for (const testCase of fixture.tool)
      expect(parseToolName(testCase.target)).toBe(testCase.value);
    for (const testCase of fixture.system)
      expect(parseSystemIndex(testCase.target)).toBe(testCase.value);
    for (const testCase of fixture.tool_result)
      expect(parseToolResultId(testCase.target)).toBe(testCase.value);
    for (const testCase of fixture.sampling)
      expect(parseSamplingField(testCase.target)).toBe(testCase.value);
    for (const testCase of fixture.provider_extras)
      expect(parseProviderExtrasKey(testCase.target)).toBe(testCase.value);
    for (const testCase of fixture.message_block) {
      const expected =
        testCase.value === null ? null : { msgIdx: testCase.value[0], blkIdx: testCase.value[1] };
      expect(parseMessageTarget(testCase.target)).toEqual(expected);
    }
  });
});
