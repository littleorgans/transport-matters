# ALP-2019 Coverage Audit

Baseline: `e7dccaab9abd4115a6ceba2e391e8772ca7635a1`

## Scope

- `api/src/transport_matters/test_track_manager_*.py`
- `api/src/transport_matters/codex/test_transport_turn_*.py`
- `api/src/transport_matters/codex/test_repair_*.py`
- `www/src/components/editor/SamplingSection.*.test.tsx`
- `www/src/hooks/useExchangeStream.*.test.tsx`
- `www/src/components/ExchangeList*.test.tsx`

## Findings

The backend transport and repair splits preserve the deleted monolithic suites by test name and assertion set.

The track manager split preserves the deleted scenarios. Several standalone lifecycle tests now run through table driven cases, and the common expected anchor assertions cover the prior `track_id`, `parent_track_id`, display name, and spawn anchor checks.

The SamplingSection and useExchangeStream splits preserve their baseline scenarios. Removed text is grouping and naming noise, not behavior coverage. The stream validation suite also adds spawn anchor propagation coverage.

ExchangeList baseline row, tree, selection, history, scroll, and Codex summary scenarios are preserved. One audit gap was found in the new anchored integration tests: they asserted presence and click behavior but not DOM row order. That coverage is restored in `ExchangeList.ordering.test.tsx`.

## Intentionally Removed Assertions

No high value assertions were intentionally removed. Textual changes are covered by shared helpers or table driven assertions in the split suites.
