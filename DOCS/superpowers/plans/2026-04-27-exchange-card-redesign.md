# Exchange Card Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign ExchangeTurnCard to orient by user prompt instead of metrics, surfacing what the exchange *is* rather than what it cost.

**Architecture:** Add `user_prompt_preview` to the backend `IndexEntry` model and propagate through all 6 construction sites. Rework the frontend card from a 3-cell inner grid to a clean 3-row layout: top-bar (TURN + model + time), middle (prompt preview or progress bar), bottom strip (INPUT / OUTPUT / TOTAL). State communicated via border color only.

**Tech Stack:** Python/Pydantic (backend), React/TypeScript/Tailwind (frontend), Vitest (unit tests), Playwright (visual tests).

---

## Design Spec

### Card layout — both Claude and Codex

**Settled (res present):**
```
┌─ top bar ──────────────────────────────────────────────────────┐
│ 007  claude-opus-4-7                              1M AGO        │
├─ middle ───────────────────────────────────────────────────────┤
│ "write me a function that parses JSON and handles…" · END_TURN  │
├─ bottom strip ─────────────────────────────────────────────────┤
│ INPUT          OUTPUT          TOTAL                            │
│ 81 tokens      51 tokens       77,219 tokens                    │
└────────────────────────────────────────────────────────────────┘
```

**Pending (res=null, Claude):**
```
┌─ top bar ──────────────────────────────────────────────────────┐
│ 007  claude-opus-4-7                              12S           │
├─ middle ───────────────────────────────────────────────────────┤
│ [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] (segments) │
├─ bottom strip ─────────────────────────────────────────────────┤
│ INPUT          OUTPUT          TOTAL                            │
│ —              —               —                                │
└────────────────────────────────────────────────────────────────┘
```

**Pending (Codex open turn):**
- Middle: segment bar + FRAMES counter (e.g. `0→12`)
- Bottom: same dashes

### Token definitions
- INPUT = `res.input_tokens` (fresh cost, no cache)
- OUTPUT = `res.output_tokens`
- TOTAL = `res.input_tokens + res.cache_creation_input_tokens + res.cache_read_input_tokens` (context footprint — the displaced "big blue number")

### State as border color (replaces STATE cell)
| State | Border |
|---|---|
| Pending (res=null, no codex_turn) | amber |
| Codex turn open | amber |
| Codex turn completed | sage |
| Codex turn failed | rose |
| Codex turn interrupted | lavender |
| Settled Claude (any stop_reason) | default |

### Model name styling (de-emphasized)
`text-[11px] uppercase tracking-widest text-txt-3 font-normal` — label register, not headline.

### Stop reason in middle row
Settled rows append `· STOP_REASON` in muted text after the prompt preview, e.g. `"write me a…" · END_TURN`.

### user_prompt_preview extraction
- Last `role="user"` message in `ir.messages`
- First `TextBlock` in that message's `content`
- Truncated to **200 chars** with `…` if longer
- `None` if no user message or no text block (tool-result-only messages)

---

## Files

### Backend
| File | Change |
|---|---|
| `api/src/manicure/storage/base.py` | Add `user_prompt_preview: str \| None = None` to `IndexEntry` |
| `api/src/manicure/exchange_stats.py` | Add `extract_user_prompt_preview(ir) -> str \| None` |
| `api/src/manicure/exchange_recorder.py` | Thread preview into both `IndexEntry(...)` calls (lines ~239, ~304) |
| `api/src/manicure/codex/exchange.py` | Thread preview into 3 `IndexEntry(...)` calls (lines ~103, ~241, ~530) |
| `api/src/manicure/storage/disk_helpers.py` | Thread preview into `IndexEntry(...)` call (line ~304) — reads from stored row, preview will be `None` for old rows |

### Frontend
| File | Change |
|---|---|
| `www/src/types.ts` | Add `user_prompt_preview?: string \| null` to `IndexEntry` |
| `www/src/components/ExchangeTurnCard.tsx` | Full card layout redesign (see below) |
| `www/src/components/ExchangeList.test.tsx` | Update assertions for new strip labels and layout |

---

## Task 1: Backend — add `user_prompt_preview` to IndexEntry

**Files:**
- Modify: `api/src/manicure/storage/base.py`
- Modify: `api/src/manicure/exchange_stats.py`
- Test: `api/src/manicure/test_exchange_recorder_emit.py` (existing, update)

- [ ] **Step 1: Write failing test for `extract_user_prompt_preview`**

Add to `api/src/manicure/test_exchange_recorder_emit.py` (or create `api/src/manicure/test_exchange_stats.py`):

```python
from manicure.exchange_stats import extract_user_prompt_preview
from manicure.ir import Message, TextBlock, ToolUseBlock, ToolResultBlock, InternalRequest
# build a minimal InternalRequest using your existing fixture helpers

def make_ir_with_last_user_text(text: str) -> InternalRequest:
    # reuse existing make_request or build minimal fixture
    ...

def test_extract_preview_returns_last_user_text():
    ir = make_ir_with_last_user_text("hello world")
    assert extract_user_prompt_preview(ir) == "hello world"

def test_extract_preview_truncates_at_200_chars():
    long = "x" * 300
    ir = make_ir_with_last_user_text(long)
    result = extract_user_prompt_preview(ir)
    assert result == "x" * 200 + "…"
    assert len(result) == 201

def test_extract_preview_none_when_no_user_message():
    # ir whose messages are all assistant role
    ...
    assert extract_user_prompt_preview(ir) is None

def test_extract_preview_none_when_last_user_has_no_text_block():
    # last user message has only ToolResultBlock content
    ...
    assert extract_user_prompt_preview(ir) is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd api && uv run pytest src/manicure/test_exchange_stats.py -v
```
Expected: ImportError or AttributeError (function not yet defined).

- [ ] **Step 3: Add field to IndexEntry**

In `api/src/manicure/storage/base.py`, add to `IndexEntry`:
```python
user_prompt_preview: str | None = None
```
Place after `mutated_manually: bool = False`.

- [ ] **Step 4: Implement `extract_user_prompt_preview`**

In `api/src/manicure/exchange_stats.py`:
```python
from manicure.ir import InternalRequest, TextBlock, ToolUseBlock

_PREVIEW_MAX_CHARS = 200

def extract_user_prompt_preview(ir: InternalRequest) -> str | None:
    for message in reversed(ir.messages):
        if message.role != "user":
            continue
        for block in message.content:
            if isinstance(block, TextBlock) and block.text:
                text = block.text.strip()
                if len(text) > _PREVIEW_MAX_CHARS:
                    return text[:_PREVIEW_MAX_CHARS] + "…"
                return text
    return None
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
cd api && uv run pytest src/manicure/test_exchange_stats.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add api/src/manicure/storage/base.py api/src/manicure/exchange_stats.py api/src/manicure/test_exchange_stats.py
git commit -m "nancy[ALP-2006]: add user_prompt_preview to IndexEntry"
```

---

## Task 2: Wire preview into all IndexEntry construction sites

**Files:**
- Modify: `api/src/manicure/exchange_recorder.py`
- Modify: `api/src/manicure/codex/exchange.py`
- Modify: `api/src/manicure/storage/disk_helpers.py`

For each `IndexEntry(...)` call, add:
```python
user_prompt_preview=extract_user_prompt_preview(ir),
```
where `ir` is the `InternalRequest` available at that callsite.

`disk_helpers.py` reconstructs from stored data and has no IR — leave `user_prompt_preview` absent (defaults to `None`).

- [ ] **Step 1: Wire `exchange_recorder.py` (~line 239)**

`exchange_recorder.py` has `ir` in scope at both IndexEntry construction sites. Add the field:
```python
entry = IndexEntry(
    ...
    user_prompt_preview=extract_user_prompt_preview(curated_ir),
)
```
Use `curated_ir` (the pipeline-modified request, same as `req_stats` uses).

Import at top: `from manicure.exchange_stats import ..., extract_user_prompt_preview`

- [ ] **Step 2: Wire `codex/exchange.py` (lines ~103, ~241, ~530)**

Each `IndexEntry(...)` in `codex/exchange.py` has access to `ir: InternalRequest`. Add:
```python
user_prompt_preview=extract_user_prompt_preview(ir),
```

- [ ] **Step 3: Run full API test suite**

```bash
cd api && uv run pytest src/ -x -q
```
Expected: same pass/fail count as before (10 pre-existing failures, rest pass).

- [ ] **Step 4: Commit**

```bash
git add api/src/manicure/exchange_recorder.py api/src/manicure/codex/exchange.py api/src/manicure/storage/disk_helpers.py
git commit -m "nancy[ALP-2006]: wire user_prompt_preview through all IndexEntry sites"
```

---

## Task 3: Frontend type + strip update

**Files:**
- Modify: `www/src/types.ts`
- Modify: `www/src/components/__test-utils__/exchangeList.ts`

- [ ] **Step 1: Add field to frontend IndexEntry**

In `www/src/types.ts`, add to `IndexEntry`:
```typescript
user_prompt_preview?: string | null;
```

- [ ] **Step 2: No test needed** — type-only change, covered by typecheck.

- [ ] **Step 3: Run typecheck**

```bash
cd www && pnpm typecheck
```
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add www/src/types.ts
git commit -m "nancy[ALP-2006]: add user_prompt_preview to frontend IndexEntry type"
```

---

## Task 4: Redesign ExchangeTurnCard

**Files:**
- Modify: `www/src/components/ExchangeTurnCard.tsx`
- Modify: `www/src/components/ExchangeList.test.tsx`

### New card structure

Grid rows: `grid-rows-[58px_minmax(86px,auto)_48px]`

**Row 1 — top bar:**
```tsx
<span className="flex items-center gap-3 border-b border-edge px-4">
  <span className="metric-num text-[14px] text-txt-2 shrink-0">
    <TurnValue turn={entry.codex_turn} fallbackIndex={turnSequence} />
  </span>
  <span className="label min-w-0 flex-1 truncate text-[11px] uppercase tracking-widest text-txt-3">
    {displayModel(entry.provider, entry.model)}
  </span>
  <span className="metric-num shrink-0 border border-edge-strong bg-canvas/35 px-3 py-1.5 text-[12px] uppercase text-txt-2">
    {isClaudePending ? formatElapsedTime(entry.ts) : formatRelativeTime(entry.ts)}
  </span>
</span>
```

**Row 2 — middle:**
- `isOpen` (pending): segment bar (full width). Codex: segment bar + FRAMES badge.
- Settled: prompt preview text + muted stop_reason suffix.

```tsx
{isOpen ? (
  <span className="flex items-center gap-3 border-b border-edge px-4 py-3">
    <span
      data-testid={`exchange-token-activity-${entry.id}`}
      className="grid w-full grid-cols-[repeat(10,minmax(0,1fr))] gap-1"
      aria-hidden
    >
      {TOKEN_SEGMENTS.map(...)}
    </span>
    {isCodexPending && (
      <span className="label shrink-0 text-[11px] text-txt-3">
        {framesDisplay}
      </span>
    )}
  </span>
) : (
  <span className="flex min-w-0 items-start border-b border-edge px-4 py-3">
    <span className="min-w-0 text-[13px] leading-snug text-txt-2 line-clamp-2">
      {entry.user_prompt_preview ?? <span className="text-txt-3">—</span>}
      {stopReason && (
        <span className="ml-2 text-[11px] uppercase text-txt-3">· {stopReason}</span>
      )}
    </span>
  </span>
)}
```

**Row 3 — bottom strip:**
- Remove TOOLS.
- INPUT = `res.input_tokens`
- OUTPUT = `res.output_tokens`
- TOTAL = `res.input_tokens + res.cache_creation_input_tokens + res.cache_read_input_tokens`
- Pending: all "—" (muted).

```typescript
function panelMetrics(entry: IndexEntry): PanelMetric[] {
  const turn = entry.codex_turn;

  // Claude rows
  if (!turn && entry.provider !== "codex") {
    if (entry.res === null) {
      return [
        { key: "input", label: "Input", value: "—" },
        { key: "output", label: "Output", value: "—" },
        { key: "total", label: "Total", value: "—" },
      ];
    }
    const total =
      entry.res.input_tokens +
      entry.res.cache_creation_input_tokens +
      entry.res.cache_read_input_tokens;
    return [
      { key: "input", label: "Input", value: formatCount(entry.res.input_tokens), unit: "tokens" },
      { key: "output", label: "Output", value: formatCount(entry.res.output_tokens), unit: "tokens" },
      { key: "total", label: "Total", value: formatCount(total), unit: "tokens" },
    ];
  }

  // Codex rows — keep existing TOOLS / TEXT / FRAMES
  const tools = turn?.tool_calls ?? entry.res?.tool_calls ?? entry.req.tools_count;
  const text = turn?.text_chars ?? entry.res?.text_chars ?? entry.req.total_chars;
  const thirdMetric = turn != null
    ? { key: "frames", label: "Frames", value: `${turn.message_range_start}->${turn.message_range_end}` }
    : { key: "messages", label: "Msgs", value: formatCount(entry.req.messages_count) };
  return [
    { key: "tools", label: "Tools", value: formatCount(tools) },
    { key: "text", label: "Text", value: formatCount(text), unit: pluralUnit(text, "char") },
    thirdMetric,
  ];
}
```

### Border color (state)

```typescript
function cardBorderClass(entry: IndexEntry, previewWaiting: boolean, isOpen: boolean): string {
  if (isOpen) return "border-amber/45 group-hover:border-amber/65";
  const turnStatus = entry.codex_turn?.status;
  if (turnStatus === "completed") return "border-sage/30 group-hover:border-sage/50";
  if (turnStatus === "failed") return "border-rose/30 group-hover:border-rose/50";
  if (turnStatus === "interrupted") return "border-lavender/30 group-hover:border-lavender/50";
  return "border-edge-strong group-hover:border-edge";
}
```

Drop the `statusDisplay()` function and `STATUS` cell entirely.

- [ ] **Step 1: Write failing tests**

Update `www/src/components/ExchangeList.test.tsx`:

```typescript
it("renders Claude settled strip as INPUT / OUTPUT / TOTAL", () => {
  renderExchangeList([
    makeEntry({
      id: "settled",
      res: {
        stop_reason: "end_turn",
        input_tokens: 81,
        output_tokens: 51,
        cache_creation_input_tokens: 60_153,
        cache_read_input_tokens: 16_985,
        text_chars: 200,
        tool_calls: 0,
      },
    }),
  ]);
  expect(screen.getByTestId("exchange-metrics-settled")).toHaveTextContent(
    "Exchange metrics: Input: 81 tokens, Output: 51 tokens, Total: 77,219 tokens",
  );
});

it("renders Claude pending strip as dashes", () => {
  renderExchangeList([makeEntry({ id: "pending", res: null })]);
  expect(screen.getByTestId("exchange-metrics-pending")).toHaveTextContent(
    "Exchange metrics: Input: —, Output: —, Total: —",
  );
});

it("renders prompt preview in settled middle row", () => {
  renderExchangeList([
    makeEntry({ id: "with-preview", res: legacyClaudeRes, user_prompt_preview: "write me a parser" }),
  ]);
  expect(screen.getByTestId("exchange-row-with-preview")).toHaveTextContent("write me a parser");
});

it("pending card shows no prompt preview", () => {
  renderExchangeList([makeEntry({ id: "pending-no-preview", res: null })]);
  expect(screen.queryByText("write me")).not.toBeInTheDocument();
  expect(screen.getByTestId(`exchange-token-activity-pending-no-preview`)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd www && pnpm test ExchangeList
```
Expected: 4 new tests fail.

- [ ] **Step 3: Implement new card layout**

Full replacement of `ExchangeTurnCard.tsx` as described in the design spec above. Key changes:
1. Remove `statusDisplay()`, `markerClasses()`, `statusClasses()`.
2. Add `cardBorderClass()`.
3. Replace 3-cell inner panel with flat top bar + middle row.
4. Update `panelMetrics()` as above.
5. Wire `useElapsedTick` to pending rows (already done).
6. TURN in top bar (remove TURN cell from inner panel).
7. Model name: `text-[11px] uppercase tracking-widest text-txt-3`.

- [ ] **Step 4: Run tests**

```bash
cd www && pnpm test ExchangeList
```
Expected: all pass.

- [ ] **Step 5: Run full check**

```bash
cd /path/to/repo && just check && just www test && just www test-visual
```

- [ ] **Step 6: Update visual snapshots if needed**

```bash
cd www && pnpm test:visual:update
```
Review diffs — layout change will touch `exchange-list-anchored` snapshot at minimum.

- [ ] **Step 7: Commit**

```bash
git add www/src/components/ExchangeTurnCard.tsx www/src/components/ExchangeList.test.tsx
git commit -m "nancy[ALP-2006]: redesign exchange card with prompt preview and border-state"
```

---

## Task 5: Update `legacyClaudeRes` fixture and old test assertions

**Files:**
- Modify: `www/src/components/__test-utils__/exchangeList.ts`
- Modify: `www/src/components/ExchangeList.test.tsx`

The existing `numbers Claude exchange turns within each track` test asserts strip text that will change. Update it to match new INPUT/OUTPUT/TOTAL format.

`legacyClaudeRes` has `input_tokens: 100, output_tokens: 50, cache_*: 0`, so TOTAL = 100.

```typescript
expect(screen.getByTestId("exchange-metrics-parent-1")).toHaveTextContent(
  "Exchange metrics: Input: 100 tokens, Output: 50 tokens, Total: 100 tokens",
);
```

---

## Self-Review Notes

- `user_prompt_preview` is optional/nullable everywhere — old stored rows and Codex provisional rows that lack IR access will show `null`, rendered as `—` in the middle row. No migration needed.
- Codex bottom strip intentionally keeps TOOLS/TEXT/FRAMES for now (different data model).
- The `tokenValue()` and `TurnValue` functions remain unchanged — TURN still displays in top bar.
- The `previewWaiting` prop (used for Codex open-turn preview) still needs to trigger `isOpen=true` → amber border + segment bar. Logic unchanged, only the cell that previously showed STATE is removed.
- `formatElapsedTime` / `useElapsedTick` already implemented in current dirty state — carry forward.
- The `exchange-token-activity-*` testid on the segment grid stays (existing test depends on it).
