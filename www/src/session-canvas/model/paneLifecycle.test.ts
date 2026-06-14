import { describe, expect, it } from "vitest";
import { capturedRunLifecyclePolicy } from "./capturedRunLifecycle";
import { resolvePaneLifecycle } from "./paneLifecycle";

describe("paneLifecycle", () => {
  it("statically resolves captured-run close policy without lab registration", () => {
    const policy = resolvePaneLifecycle({
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: "claude:k1",
    });

    expect(policy.onClose).toBe(capturedRunLifecyclePolicy.onClose);
  });
});
