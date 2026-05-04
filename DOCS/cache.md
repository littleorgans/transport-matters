# What the usage numbers show

| # | Description | tools | input_tokens | cache_write | cache_read |
|---|---|---|---|---|---|
| 3 | 148 full, first | 148 | 3,782 | **57,157** | 0 |
| 4 | 148 full, next turn | 148 | 4,457 | 0 | **57,157** ✓ |
| 5 | 148 → 145 (trim 3 tail) | 145 | 4,656 | **56,855** | 0 (miss) |
| 6 | 145 next turn | 145 | 4,879 | 0 | **56,855** ✓ |
| 7 | 145 next turn | 145 | 5,835 | 0 | **56,855** ✓ |
| 8 | 145 → 146 (different tail trim) | 146 | 6,224 | **56,958** | 0 (miss) |
| 9 | 146 → 148 (back to full) | 148 | 7,996 | 0 | **57,157** ✓ |
| 10 | 148 next turn | 148 | 8,953 | 0 | **57,157** ✓ |
| 11 | 148 → 144 (trim from start) | 144 | 9,257 | **55,131** | 0 (miss) |

Three things are now empirically locked down:

**1. Any tool mutation is a full cache miss on the turn it happens.** Not partial. Zero cache_read. Trim from start, trim from end, swap two at the tail — the server treats them all identically: full recompute of the entire cacheable prefix, full write of a new cache entry sized to the new tool chest.

**2. Unchanged tools cache fine turn-to-turn.** Once the new configuration is written (the mutation turn), subsequent turns at the same tool count hit cleanly. Entries 6, 7 at 145 tools all read 56,855.

**3. TTL is 1 hour and cached configurations coexist.** Entry 9 went back to 148 tools and hit `cache_read=57,157`, the exact number from entry 3's write three minutes earlier. Multiple configurations (148 cache from entry 3, 145 cache from entry 5, 146 cache from entry 8) are all alive simultaneously in the cache store. The LRU can hold many tool-configurations as long as each was written and TTL has not expired.

## The surprise

I expected \"append at tail\" to extend the cache. **It did not.** Entry 8 goes from a 145-tool cache to a 146-tool request that shares the first 145 tool-array bytes, and it still misses.

I went and pulled the raw request to figure out why. Claude Code sets **three** `cache_control` markers, and none of them are where I assumed they would be:

1. On the user message text \"Hello\" (inside `messages`)
2. On the first `system` text block (\"You are Claude Code...\")
3. On the *last* system text block (ending with your recent git commit messages)

All with `ttl: 1h`. **Zero markers on the tools array.**

In the Anthropic effective-prompt order, the prompt flows `system → tools → messages`. The markers are placed on the system blocks and on message content, with nothing around the tools block. So the cache entries that get written span content that *straddles* the tools array: the cached prefix must include all of system + all of tools + part of messages, depending on which marker you are reading against.

That means the tools array is **byte-embedded inside a cache entry that extends past it**. Any byte change inside that array invalidates the cache entry it sits inside, because the cached entry's hash is over the full prefix up to the marker, including the tool bytes. There is no such thing as a partial match \"up to the end of the tools array\" because no marker lives there.

This is why **adding at the tail did not extend the cache in entry 8**: the byte position where the marker sits is past the tools array, and the bytes between the end of tools and the marker are different whenever tool count changes.

## The architectural insight this unlocks

Stuart, this is the piece that makes Transport Matters genuinely interesting in a way I did not see an hour ago. **Cache breakpoint placement is a policy decision, and Claude Code's policy is not the only one.**

Transport Matters sits in the request path. Transport Matters can *rewrite the cache_control markers* on the way to Anthropic. The Anthropic API allows up to 4 breakpoints per request; Claude Code uses 3; there is a free slot. Transport Matters could add a 4th marker at the end of the tools block, creating a tools-independent cache segment. Suddenly:

- System blocks cache independently.
- Tools block caches independently.
- Messages cache independently (using Claude Code's existing marker).

In that world, **appending a tool at the tail would in fact extend the tools-block cache**, because the marker now lives exactly at the tools-array boundary and the hash is over the tools array alone. Remove a tool from the tail and the new shorter cache gets written but earlier entries remain alive for restoration.

This means:

**Capability 2 (per-request pruning)** is doubly dead under the current Claude Code marker layout. Not only does it lose the attention-quality argument to quality-preserving baselines, it incurs a full cache miss every single time we intervene. It is experimentation theater.

**Capability 3 (JIT tool and context delivery)**, under the rewritten-marker policy, is cache-aligned *and* attention-improving. Transport Matters adds tools as the agent earns them, and each addition extends the tools-block cache instead of busting it. The 1h TTL means realistic sessions can span the full idle window without cold-starts.

And there is a second-order benefit. Transport Matters already intermediates the request. If Transport Matters takes ownership of cache_control placement, it becomes a dedicated optimization surface — users can write rules like \"always place a marker on the tools block\" or \"put the system prompt in its own 1h block\" without having to patch their client. **Cache policy becomes a Transport Matters feature**, not a client concern.

## What the test did not yet answer

Stuart's test kept Claude Code's existing markers untouched. We have not yet confirmed that *adding a Transport Matters-controlled marker on the tools block* actually produces the append-extends-cache behavior in practice. That is the next spike, and it is small:

1. Capture a real request via Transport Matters.
2. Add a 4th `cache_control: ephemeral 1h` marker on the last tool in the tools array.
3. Fire the request. Observe `cache_creation_input_tokens` split across `ephemeral_5m` and `ephemeral_1h`.
4. Fire a second request that adds one tool at the end.
5. Check `cache_read_input_tokens`. If it shows a hit equal to the prior tools-block cache size, prefix extension works and capability 3 is cache-aligned by construction.

This is maybe 30 minutes of work and it is the single test that determines whether JIT can be shipped cleanly.

## My read on where you are

You have just moved the question from \"does pruning save tokens\" to \"does JIT extend cache\" — the latter is a much better framing because the answer directly sells capability 3 and directly justifies Transport Matters owning the cache_control policy layer.

Two things before we build the next spike:

1. **Are you on board with the reframe that Transport Matters should own cache_control placement**? This is a meaningful positioning shift: Transport Matters goes from \"intercept for curation\" to \"intercept for curation *and* cache shaping.\" I want to make sure that lands before we design around it.
2. **Do you want me to save the cache semantics we just learned to context-matters**? The findings from this spike (Claude Code's marker placement, the empirical no-partial-hit behavior, the 1h TTL) are the kind of thing that will matter across sessions and should not live only in this conversation.
