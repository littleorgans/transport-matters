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
        cli: "codex",
        status: "active",
        limit: 25,
        offset: 5,
      }),
    ).toBe(
      "/api/sessions?owner=local&limit=25&offset=5&workspace_hash=hash-1&cli=codex&status=active",
    );
  });

  it("uses the shared API transport", async () => {
    const seenPaths: string[] = [];
    const session = makeSessionSummary();
    installMockTransport((path) => {
      seenPaths.push(path);
      return jsonResponse([session]);
    });

    await expect(listSessions({ owner: "local", workspaceHash: "hash-1" })).resolves.toEqual([
      session,
    ]);
    expect(seenPaths).toEqual([
      "/api/sessions?owner=local&limit=50&offset=0&workspace_hash=hash-1",
    ]);
  });

  it("throws detail from failed session lookups", async () => {
    installMockTransport(() => jsonResponse({ detail: "session store down" }, 503));

    await expect(listSessions({ owner: "local" })).rejects.toThrow("Failed to fetch sessions: 503");
  });
});
