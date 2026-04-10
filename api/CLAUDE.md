# Python conventions

## Async boundary

- I/O: async (hooks, routes, storage)
- Pure computation: sync (pipeline actions, rule matching, adapter parsing)

## Types

- Builtins only: `list[str]`, `dict[str, Any]`, `X | None`, `X | Y`
- Annotate all return types
- `Any` requires a comment explaining why

## Pydantic

- v2 idioms: `model_config = ConfigDict(...)`, `model_validate()`, `model_dump(mode="json")`
- IR models are `frozen=True` — pipeline actions return new instances, never mutate

## ABC vs Protocol

- Runtime dispatch (adapters, storage): ABC
- Shape-only contracts: Protocol

## Import DAG

No cycles. Dependency order:

```bash
ir → adapters → rules → pipeline → storage → breakpoint → server
```

`ir.py` imports nothing from `manicure`.

## Tests
- Unit tests are colocated: `src/manicure/foo/test_bar.py` lives next to `bar.py`
- Integration tests live in `tests/integration/`

## Errors

- Domain exceptions in `exceptions.py`, translated at the FastAPI layer
- Always chain: `raise X from original`
- Never swallow silently
