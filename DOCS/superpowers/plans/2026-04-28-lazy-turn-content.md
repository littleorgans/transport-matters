# Lazy Turn Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the denormalized `user_prompt_preview` field on `IndexEntry` with a lazy-fetched per-card endpoint that returns full last-user-message text and full assistant-response text, enabling side-by-side request/response rendering on the Exchange card.

**Architecture:** Add a thin `GET /api/exchanges/{id}/turn-content` endpoint that reuses the already-parsed IR objects from `storage.read_exchange()`. New extractor `extract_response_text(res_ir)` mirrors the existing user-side extractor: prefer `TextBlock`, fall back to `ToolUseBlock` (JSON of input) and `ThinkingBlock` (XML-tagged). Frontend gets a React Query hook keyed on `["turn-content", id]`; `ExchangeTurnCard` renders two `ExchangePreview` columns fed by this hook. The legacy preview field, extractor, and constant are removed; Transport Matters has no users so the storage cache is nuked on schema change rather than migrated.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic v2 (frozen IR), React 18 / TypeScript / `@tanstack/react-query` v5, Vitest, Playwright.

---

## File Structure

**Backend (Python):**
- Modify `api/src/transport_matters/exchange_stats.py` — add `extract_response_text`, add cap-free `extract_user_prompt_text`, drop `extract_user_prompt_preview` and `_PREVIEW_MAX_CHARS` after switchover
- Modify `api/src/transport_matters/test_exchange_stats.py` — add tests for new extractors, drop tests for removed function
- Modify `api/src/transport_matters/api/v1/exchanges.py` — add `TurnContentResponse` model and `GET /{exchange_id}/turn-content` route
- Create `api/src/transport_matters/api/v1/test_exchanges_turn_content.py` — integration test for the new route
- Modify `api/src/transport_matters/storage/base.py` — drop `user_prompt_preview` field from `IndexEntry`
- Modify `api/src/transport_matters/exchange_recorder.py` — drop `user_prompt_preview=` kwargs and import
- Modify `api/src/transport_matters/codex/exchange.py` — drop `user_prompt_preview=` kwargs and import

**Frontend (TypeScript):**
- Modify `www/src/api.ts` — add `fetchTurnContent` and `TurnContent` type
- Modify `www/src/types.ts` — drop `user_prompt_preview` from `IndexEntry`
- Create `www/src/hooks/useTurnContent.ts` — React Query hook
- Create `www/src/hooks/useTurnContent.test.ts` — vitest hook test
- Modify `www/src/hooks/useExchangeStream.ts` — invalidate `["turn-content", id]` on stream events
- Modify `www/src/components/ExchangeTurnCard.tsx` — render side-by-side via hook
- Modify `www/src/components/ExchangeList.tsx` — bump `EXCHANGE_ROW_HEIGHT` for new height
- Modify `www/src/components/ExchangeList.test.tsx` — adjust row-height assertions, drop preview-related expectations

---

## Task 1: Backend extractor for response text

**Files:**
- Modify: `api/src/transport_matters/exchange_stats.py`
- Test: `api/src/transport_matters/test_exchange_stats.py`

- [ ] **Step 1: Write failing tests for `extract_response_text`**

Append to `api/src/transport_matters/test_exchange_stats.py`:

```python
from transport_matters.exchange_stats import extract_response_text
from transport_matters.ir import (
    InternalResponse,
    ThinkingBlock,
    ToolUseBlock,
    UsageStats,
)


def _make_res(content: list) -> InternalResponse:
    return InternalResponse(
        id="msg_test",
        model="claude-opus-4-7",
        provider="anthropic",
        content=content,
        stop_reason="end_turn",
        usage=UsageStats(input_tokens=0, output_tokens=0),
    )


def test_extract_response_text_returns_first_text_block() -> None:
    res = _make_res([TextBlock(text="hello"), TextBlock(text="world")])
    assert extract_response_text(res) == "hello\nworld"


def test_extract_response_text_falls_back_to_tool_use_input_json() -> None:
    res = _make_res(
        [ToolUseBlock(id="toolu_01", name="Read", input={"path": "/tmp/x"})]
    )
    assert extract_response_text(res) == '{"path": "/tmp/x"}'


def test_extract_response_text_prefers_text_over_tool_use() -> None:
    res = _make_res(
        [
            ToolUseBlock(id="toolu_01", name="Read", input={"path": "/tmp/x"}),
            TextBlock(text="answer"),
        ]
    )
    assert extract_response_text(res) == "answer"


def test_extract_response_text_wraps_thinking_block_in_xml() -> None:
    res = _make_res([ThinkingBlock(text="reasoning step")])
    assert extract_response_text(res) == "<thinking>reasoning step</thinking>"


def test_extract_response_text_returns_none_when_empty() -> None:
    res = _make_res([])
    assert extract_response_text(res) is None


def test_extract_response_text_returns_none_when_only_unknown() -> None:
    from transport_matters.ir import UnknownBlock

    res = _make_res([UnknownBlock(type="weird", raw={"foo": "bar"})])
    assert extract_response_text(res) is None
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd api && uv run pytest src/transport_matters/test_exchange_stats.py -k extract_response_text -v
```

Expected: 6 failures with `ImportError: cannot import name 'extract_response_text'`.

- [ ] **Step 3: Implement `extract_response_text`**

Add to `api/src/transport_matters/exchange_stats.py` (after `_flatten_user_text`, before `build_req_stats`):

```python
import json

from transport_matters.ir import (
    ContentBlock,
    InternalRequest,
    InternalResponse,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def extract_response_text(res: InternalResponse) -> str | None:
    """Pick text from the most informative response block.

    TextBlocks join with newlines. Falls back to ToolUseBlock input as JSON,
    then ThinkingBlock wrapped as <thinking>…</thinking>. Returns None when
    no renderable block is present.
    """
    text_parts = [b.text for b in res.content if isinstance(b, TextBlock) and b.text]
    if text_parts:
        return "\n".join(text_parts)
    for block in res.content:
        if isinstance(block, ToolUseBlock):
            return json.dumps(block.input)
        if isinstance(block, ThinkingBlock):
            return f"<thinking>{block.text}</thinking>"
    return None
```

(Add `ThinkingBlock` to existing import list if not already present.)

- [ ] **Step 4: Run tests to verify pass**

```bash
cd api && uv run pytest src/transport_matters/test_exchange_stats.py -k extract_response_text -v
```

Expected: 6 pass.

- [ ] **Step 5: Commit**

```bash
git add api/src/transport_matters/exchange_stats.py api/src/transport_matters/test_exchange_stats.py
git commit -m "nancy[ALP-2006]: add extract_response_text helper"
```

---

## Task 2: Backend extractor for full user prompt text (no cap)

**Files:**
- Modify: `api/src/transport_matters/exchange_stats.py`
- Test: `api/src/transport_matters/test_exchange_stats.py`

- [ ] **Step 1: Write failing test for `extract_user_prompt_text`**

Append to `test_exchange_stats.py`:

```python
from transport_matters.exchange_stats import extract_user_prompt_text


def test_extract_user_prompt_text_returns_full_text_uncapped() -> None:
    long = "x" * 5000
    ir = _make_ir([_user([TextBlock(text=long)])])
    assert extract_user_prompt_text(ir) == long


def test_extract_user_prompt_text_strips_whitespace() -> None:
    ir = _make_ir([_user([TextBlock(text="  hi  ")])])
    assert extract_user_prompt_text(ir) == "hi"


def test_extract_user_prompt_text_returns_none_when_empty() -> None:
    ir = _make_ir([_assistant("only assistant")])
    assert extract_user_prompt_text(ir) is None


def test_extract_user_prompt_text_falls_back_to_tool_result() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[TextBlock(text="tool output")],
    )
    ir = _make_ir([_user([tool_result])])
    assert extract_user_prompt_text(ir) == "tool output"
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd api && uv run pytest src/transport_matters/test_exchange_stats.py -k extract_user_prompt_text -v
```

Expected: 4 import failures.

- [ ] **Step 3: Implement `extract_user_prompt_text`**

Add to `exchange_stats.py` (next to `extract_user_prompt_preview`):

```python
def extract_user_prompt_text(ir: InternalRequest) -> str | None:
    """Full last-user-message text, uncapped. Frontend handles classification."""
    for message in reversed(ir.messages):
        if message.role != "user":
            continue
        text = _flatten_user_text(message.content)
        stripped = text.strip()
        return stripped or None
    return None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd api && uv run pytest src/transport_matters/test_exchange_stats.py -k extract_user_prompt_text -v
```

Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add api/src/transport_matters/exchange_stats.py api/src/transport_matters/test_exchange_stats.py
git commit -m "nancy[ALP-2006]: add extract_user_prompt_text uncapped helper"
```

---

## Task 3: Backend turn-content endpoint

**Files:**
- Modify: `api/src/transport_matters/api/v1/exchanges.py`
- Create: `api/src/transport_matters/api/v1/test_exchanges_turn_content.py`

- [ ] **Step 1: Write failing route test**

Create `api/src/transport_matters/api/v1/test_exchanges_turn_content.py`:

```python
"""Tests for GET /api/exchanges/{id}/turn-content."""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.ir import (
    InternalResponse,
    TextBlock,
    UsageStats,
)
from transport_matters.storage.base import ExchangeArtifacts

from .test_exchanges_support import make_index_entry, make_ir

if TYPE_CHECKING:
    from httpx import AsyncClient


async def _seed_complete(exchange_id: str = "ex-001") -> None:
    from transport_matters.storage import get_storage

    storage = await get_storage()
    entry = make_index_entry(exchange_id)
    res_ir = InternalResponse(
        id=f"msg_{exchange_id}",
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        content=[TextBlock(text="world")],
        stop_reason="end_turn",
        usage=UsageStats(input_tokens=1, output_tokens=1),
    )
    artifacts = ExchangeArtifacts(
        request_raw=b"{}",
        request_ir=make_ir(),
        response_ir=res_ir,
    )
    await storage.persist_exchange(entry, artifacts)


async def test_turn_content_returns_user_and_response_text(client: "AsyncClient") -> None:
    await _seed_complete()
    resp = await client.get("/api/exchanges/ex-001/turn-content")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_text"] == "hi"
    assert body["response_text"] == "world"
    assert body["stop_reason"] == "end_turn"


async def test_turn_content_returns_404_for_missing(client: "AsyncClient") -> None:
    resp = await client.get("/api/exchanges/missing/turn-content")
    assert resp.status_code == 404


async def test_turn_content_null_response_when_in_flight(client: "AsyncClient") -> None:
    from transport_matters.storage import get_storage

    storage = await get_storage()
    entry = make_index_entry("ex-pending")
    artifacts = ExchangeArtifacts(
        request_raw=b"{}",
        request_ir=make_ir(),
        response_ir=None,
    )
    await storage.persist_exchange(entry, artifacts)

    resp = await client.get("/api/exchanges/ex-pending/turn-content")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_text"] == "hi"
    assert body["response_text"] is None
    assert body["stop_reason"] is None
```

The `client` fixture and storage isolation come from `api/src/transport_matters/api/v1/conftest.py` automatically.

- [ ] **Step 2: Run test to verify failure**

```bash
cd api && uv run pytest src/transport_matters/api/v1/test_exchanges_turn_content.py -v
```

Expected: tests fail with 404 (route not registered).

- [ ] **Step 3: Implement endpoint**

Add to `api/src/transport_matters/api/v1/exchanges.py` (after `PipelineTokensResponse` class definition, near line 178):

```python
class TurnContentResponse(BaseModel):
    """Lazy per-card payload: full last-user text and full assistant text."""

    user_text: str | None
    response_text: str | None
    stop_reason: str | None


@router.get("/{exchange_id}/turn-content")
async def get_turn_content(
    exchange_id: str,
    storage: StorageBackend = Depends(get_storage),
) -> TurnContentResponse:
    try:
        artifacts = await storage.read_exchange(exchange_id)
    except FileNotFoundError as exc:
        raise NotFoundError(detail=f"Exchange {exchange_id} not found") from exc

    user_text = extract_user_prompt_text(artifacts.request_ir)
    response_text = (
        extract_response_text(artifacts.response_ir)
        if artifacts.response_ir is not None
        else None
    )
    stop_reason = (
        artifacts.response_ir.stop_reason if artifacts.response_ir is not None else None
    )
    return TurnContentResponse(
        user_text=user_text,
        response_text=response_text,
        stop_reason=stop_reason,
    )
```

Add imports at the top of the file:

```python
from transport_matters.exchange_stats import extract_response_text, extract_user_prompt_text
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd api && uv run pytest src/transport_matters/api/v1/test_exchanges_turn_content.py -v
```

Expected: 3 pass.

- [ ] **Step 5: Run full backend test suite**

```bash
cd api && uv run pytest -x
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add api/src/transport_matters/api/v1/exchanges.py api/src/transport_matters/api/v1/test_exchanges_turn_content.py
git commit -m "nancy[ALP-2006]: add turn-content endpoint"
```

---

## Task 4: Frontend API client + types

**Files:**
- Modify: `www/src/api.ts`
- Modify: `www/src/types.ts`

- [ ] **Step 1: Add `TurnContent` type**

Append to `www/src/types.ts`:

```typescript
export interface TurnContent {
  user_text: string | null;
  response_text: string | null;
  stop_reason: string | null;
}
```

- [ ] **Step 2: Add `fetchTurnContent` to API client**

Append to `www/src/api.ts`:

```typescript
import type { TurnContent } from "./types";

export async function fetchTurnContent(id: string): Promise<TurnContent> {
  const res = await fetch(`/api/exchanges/${id}/turn-content`);
  if (!res.ok) {
    throw new Error(`Failed to fetch turn content for ${id}: ${res.status}`);
  }
  return res.json();
}
```

(If `import type { TurnContent }` would conflict with existing import block, fold into existing import.)

- [ ] **Step 3: Run typecheck**

```bash
cd www && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add www/src/api.ts www/src/types.ts
git commit -m "nancy[ALP-2006]: add fetchTurnContent client helper"
```

---

## Task 5: Frontend `useTurnContent` hook

**Files:**
- Create: `www/src/hooks/useTurnContent.ts`
- Create: `www/src/hooks/useTurnContent.test.ts`

- [ ] **Step 1: Write failing test**

Create `www/src/hooks/useTurnContent.test.ts`:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTurnContent } from "./useTurnContent";

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useTurnContent", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches turn content for a given id", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({
        user_text: "hi",
        response_text: "hello",
        stop_reason: "end_turn",
      }),
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useTurnContent("ex-001"), {
      wrapper: wrapper(client),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toEqual({
      user_text: "hi",
      response_text: "hello",
      stop_reason: "end_turn",
    });
    expect(fetch).toHaveBeenCalledWith("/api/exchanges/ex-001/turn-content");
  });

  it("does not fetch when id is empty", () => {
    const client = new QueryClient();
    renderHook(() => useTurnContent(""), { wrapper: wrapper(client) });
    expect(fetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd www && npx vitest run src/hooks/useTurnContent.test.ts
```

Expected: import failure.

- [ ] **Step 3: Implement hook**

Create `www/src/hooks/useTurnContent.ts`:

```typescript
import { useQuery } from "@tanstack/react-query";
import { fetchTurnContent } from "../api";
import type { TurnContent } from "../types";

export function useTurnContent(id: string) {
  return useQuery<TurnContent>({
    queryKey: ["turn-content", id],
    queryFn: () => fetchTurnContent(id),
    enabled: id.length > 0,
    staleTime: Infinity,
  });
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd www && npx vitest run src/hooks/useTurnContent.test.ts
```

Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add www/src/hooks/useTurnContent.ts www/src/hooks/useTurnContent.test.ts
git commit -m "nancy[ALP-2006]: add useTurnContent React Query hook"
```

---

## Task 6: Stream invalidation for turn-content

**Files:**
- Modify: `www/src/hooks/useExchangeStream.ts`

- [ ] **Step 1: Locate existing exchange invalidation**

Open `www/src/hooks/useExchangeStream.ts` line 252:

```typescript
void queryClient.invalidateQueries({ queryKey: ["exchange", entry.id] });
```

- [ ] **Step 2: Add turn-content invalidation alongside it**

Replace that line with:

```typescript
void queryClient.invalidateQueries({ queryKey: ["exchange", entry.id] });
void queryClient.invalidateQueries({ queryKey: ["turn-content", entry.id] });
```

- [ ] **Step 3: Locate existing remove on delete (line 275)**

```typescript
queryClient.removeQueries({ queryKey: ["exchange", data.id], exact: true });
```

- [ ] **Step 4: Add turn-content remove alongside it**

Replace that line with:

```typescript
queryClient.removeQueries({ queryKey: ["exchange", data.id], exact: true });
queryClient.removeQueries({ queryKey: ["turn-content", data.id], exact: true });
```

- [ ] **Step 5: Run existing stream tests**

```bash
cd www && npx vitest run src/hooks/useExchangeStream
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add www/src/hooks/useExchangeStream.ts
git commit -m "nancy[ALP-2006]: invalidate turn-content cache on stream events"
```

---

## Task 7: Side-by-side rendering on `ExchangeTurnCard`

**Files:**
- Modify: `www/src/components/ExchangeTurnCard.tsx`
- Modify: `www/src/components/ExchangeList.tsx`
- Modify: `www/src/components/ExchangeList.test.tsx`

- [ ] **Step 1: Adjust row height constants**

In `www/src/components/ExchangeList.tsx` line 25:

Replace:
```typescript
const EXCHANGE_ROW_HEIGHT = 196;
```

with:
```typescript
const EXCHANGE_ROW_HEIGHT = 250;
```

- [ ] **Step 2: Update outer button min-h in `ExchangeTurnCard.tsx`**

Replace all instances of `min-h-[196px]` with `min-h-[250px]`:

```bash
cd www && sed -i '' 's/min-h-\[196px\]/min-h-[250px]/g' src/components/ExchangeTurnCard.tsx
```

- [ ] **Step 3: Adjust inner grid rows**

In `ExchangeTurnCard.tsx`, find the inner grid span (around line 267 — note `min-h-[250px]` after Step 2's sed pass):

Replace `grid-rows-[58px_minmax(86px,auto)_48px]` with `grid-rows-[58px_140px_48px]`. Final shape:

```tsx
className={`relative grid min-h-[250px] min-w-0 grid-rows-[58px_140px_48px] overflow-hidden border bg-[linear-gradient(180deg,#101112,#070707)] shadow-[inset_0_1px_0_rgb(var(--highlight-rgb)/0.07),inset_0_-22px_45px_rgb(var(--shadow-rgb)/0.35)] transition-colors duration-150 ${borderClass} ${isSubagent ? "min-h-[250px]" : ""}`}
```

- [ ] **Step 4: Wire `useTurnContent` and replace middle row**

In `ExchangeTurnCard.tsx`, add the hook import at the top:

```tsx
import { useTurnContent } from "../hooks/useTurnContent";
```

Inside `ExchangeTurnCard`, after `const stopReason = ...`:

```tsx
const turnContent = useTurnContent(entry.id);
const userText = turnContent.data?.user_text ?? null;
const responseText = turnContent.data?.response_text ?? null;
const isLoadingTurn = turnContent.isLoading;
```

Replace the entire non-open middle-row block (the `<span className="flex min-w-0 items-start border-b border-edge px-4 py-3">…</span>` block, currently at lines ~327-338):

```tsx
<span className="grid min-w-0 grid-cols-2 border-b border-edge">
  <span className="flex min-w-0 items-start border-r border-edge px-4 py-3">
    {userText ? (
      <ExchangePreview text={userText} />
    ) : (
      <span className="min-w-0 text-[13px] leading-snug text-txt-3">
        {isLoadingTurn ? "…" : "—"}
      </span>
    )}
  </span>
  <span className="flex min-w-0 items-start px-4 py-3">
    {responseText ? (
      <ExchangePreview text={responseText} stopReason={stopReason} />
    ) : (
      <span className="min-w-0 text-[13px] leading-snug text-txt-3">
        {isLoadingTurn ? "…" : "—"}
        {!isLoadingTurn && stopReason && (
          <span className="ml-2 text-[11px] uppercase text-txt-3">· {stopReason}</span>
        )}
      </span>
    )}
  </span>
</span>
```

The horizontal-ellipsis `…` is a deliberate loading affordance that flashes briefly on first paint before React Query resolves. Errors fall through silently to em-dash — React Query's default retry behavior covers transient failures, and the inspector is single-user / localhost so persistent errors are debuggable from the browser devtools.

- [ ] **Step 4b: Bump `MAX_LINES` in `ExchangePreview` for the taller row**

In `www/src/components/ExchangePreview.tsx` line 17, replace:

```typescript
const MAX_LINES = 3;
```

with:

```typescript
const MAX_LINES = 5;
```

Also bump the mono-branch overflow in `ExchangePreview.tsx` line 76 — replace `max-h-[60px]` with `max-h-[100px]` so JSON / code blocks can fill the new vertical room. Update affected tests in `ExchangePreview.test.tsx`: the JSON-truncation test asserts 4 lines (3 + ellipsis); update it to 6 lines (5 + ellipsis).

- [ ] **Step 5: Update row-height test assertion**

In `www/src/components/ExchangeList.test.tsx` line 385:

Replace:
```typescript
expect(row).toHaveClass("min-h-[196px]");
```

with:
```typescript
expect(row).toHaveClass("min-h-[250px]");
```

- [ ] **Step 6: Run typecheck and tests**

```bash
cd www && npx tsc --noEmit && npx vitest run
```

Expected: all pass.

- [ ] **Step 7: Visual smoke test**

Run dev server and confirm the redesigned card renders:

```bash
just www dev
```

Open `http://localhost:5173`, observe a card with both columns populated with type-aware previews.

- [ ] **Step 8: Commit**

```bash
git add www/src/components/ExchangeTurnCard.tsx www/src/components/ExchangeList.tsx www/src/components/ExchangeList.test.tsx
git commit -m "nancy[ALP-2006]: side-by-side prompt/response on exchange card"
```

---

## Task 8: Drop legacy `user_prompt_preview` field and extractor

**Files:**
- Modify: `api/src/transport_matters/storage/base.py`
- Modify: `api/src/transport_matters/exchange_stats.py`
- Modify: `api/src/transport_matters/test_exchange_stats.py`
- Modify: `api/src/transport_matters/exchange_recorder.py`
- Modify: `api/src/transport_matters/codex/exchange.py`
- Modify: `www/src/types.ts`

- [ ] **Step 1: Remove field from `IndexEntry`**

In `api/src/transport_matters/storage/base.py` line 124, delete:

```python
    user_prompt_preview: str | None = None
```

- [ ] **Step 2: Remove backend call sites**

In `api/src/transport_matters/exchange_recorder.py`:
- Line 17: drop `extract_user_prompt_preview` from the import list (keep other imports)
- Lines 251 and 316: delete the entire `user_prompt_preview=extract_user_prompt_preview(curated_ir),` line

In `api/src/transport_matters/codex/exchange.py`:
- Line 37: drop `extract_user_prompt_preview` from the import list
- Lines 119, 259, 542: delete each `user_prompt_preview=extract_user_prompt_preview(...)` line

- [ ] **Step 3: Remove extractor function and constant**

In `api/src/transport_matters/exchange_stats.py`:

Delete `_PREVIEW_MAX_CHARS = 1000` (line 22) and the entire `extract_user_prompt_preview` function definition (lines 25-39).

- [ ] **Step 4: Remove extractor tests**

In `api/src/transport_matters/test_exchange_stats.py`, delete the import of `extract_user_prompt_preview` and every test starting `test_extract_preview_*` (the full original test set, not the new `extract_user_prompt_text` tests).

- [ ] **Step 5: Remove frontend type field**

In `www/src/types.ts` line 67, delete:

```typescript
  user_prompt_preview?: string | null;
```

- [ ] **Step 6: Search for stragglers**

```bash
cd /Users/alphab/Dev/LLM/DEV/helioy/transport-matters-worktrees/nancy-ALP-2006
grep -rn "user_prompt_preview\|extract_user_prompt_preview\|_PREVIEW_MAX_CHARS" api/ www/ --include="*.py" --include="*.ts" --include="*.tsx"
```

Expected: no matches.

- [ ] **Step 7: Run full test suites**

```bash
cd api && uv run pytest -x
cd ../www && npx tsc --noEmit && npx vitest run
```

Expected: all pass.

- [ ] **Step 8: Nuke local cache (no backcompat — schema changed)**

```bash
rm -rf ~/.transport-matters/workspaces
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "nancy[ALP-2006]: drop user_prompt_preview field and extractor"
```

---

## Task 9: Type-check, full test, integration smoke

**Files:** none modified.

- [ ] **Step 1: Backend typecheck**

```bash
cd api && uv run mypy src/transport_matters
```

Expected: clean.

- [ ] **Step 2: Backend tests**

```bash
cd api && uv run pytest
```

Expected: all pass.

- [ ] **Step 3: Frontend typecheck**

```bash
cd www && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Frontend tests**

```bash
cd www && npx vitest run
```

Expected: all pass.

- [ ] **Step 5: Playwright visual snapshots**

```bash
cd www && npx playwright test
```

Expected: snapshots updated where the card visually changed; review diffs and commit if intentional.

- [ ] **Step 6: Manual end-to-end smoke**

Start the transport-matters proxy + dev frontend, send one Anthropic request through, observe a card render with side-by-side preview columns:

```bash
just dev
```

In another terminal:
```bash
ANTHROPIC_BASE_URL=http://localhost:8000 claude -p "say hi"
```

Then navigate to the inspector and confirm the new card renders with both columns populated and the legacy preview field is gone from the index payload (`curl -s localhost:8000/api/exchanges | jq '.entries[0]'`).

- [ ] **Step 7: Commit any updated snapshots**

```bash
git add www/tests/
git commit -m "nancy[ALP-2006]: refresh playwright snapshots for lazy turn-content"
```
