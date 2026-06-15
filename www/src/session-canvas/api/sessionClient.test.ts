import { afterEach, describe, expect, it } from "vitest";
import {
  installMockTransport,
  jsonResponse,
  makeSessionSummary,
  restoreTransport,
} from "../testUtils";
import { listSessions, sessionsPath } from "./sessionClient";

describe("sessionClient", () => {
  afterEach(() => restoreTransport());

  it("builds session list params from filters", () => {
    expect(
      sessionsPath({
        owner: "local",
        workspaceHash: "hash-1",
        purpose: "continuation",
        includeInternal: true,
        limit: 25,
        cursor: "cursor-1",
      }),
    ).toBe(
      "/v1/sessions?owner=local&limit=25&workspaceId=hash-1&purpose=continuation&includeInternal=true&cursor=cursor-1",
    );
  });

  it("uses the shared API transport", async () => {
    const seenPaths: string[] = [];
    const session = makeSessionSummary();
    installMockTransport((path) => {
      seenPaths.push(path);
      return jsonResponse({ items: [session], nextCursor: null });
    });

    await expect(listSessions({ owner: "local", workspaceHash: "hash-1" })).resolves.toEqual([
      session,
    ]);
    expect(seenPaths).toEqual(["/v1/sessions?owner=local&limit=50&workspaceId=hash-1"]);
  });

  it("throws detail from failed session lookups", async () => {
    installMockTransport(() => jsonResponse({ detail: "session store down" }, 503));

    await expect(listSessions({ owner: "local" })).rejects.toThrow("Failed to fetch sessions: 503");
  });
});
