from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Jsonb

JsonObject = dict[str, Any]

EXCHANGE_ID_KEYS = ("exchange_id", "exchangeId")
EXCHANGE_ID_CONTAINERS = (
    "transport_matters",
    "transportMatters",
    "transport",
    "wire",
    "correlation",
    "turn",
)


@dataclass(frozen=True)
class ExchangeIdContainmentProbe:
    name: str
    container: str | None
    key: str


EXCHANGE_ID_CONTAINMENT_PROBES = (
    ExchangeIdContainmentProbe("top_snake", None, "exchange_id"),
    ExchangeIdContainmentProbe("top_camel", None, "exchangeId"),
    ExchangeIdContainmentProbe("transport_matters_snake", "transport_matters", "exchange_id"),
    ExchangeIdContainmentProbe("transport_matters_camel", "transport_matters", "exchangeId"),
    ExchangeIdContainmentProbe("transport_matters_js_snake", "transportMatters", "exchange_id"),
    ExchangeIdContainmentProbe("transport_matters_js_camel", "transportMatters", "exchangeId"),
    ExchangeIdContainmentProbe("transport_snake", "transport", "exchange_id"),
    ExchangeIdContainmentProbe("transport_camel", "transport", "exchangeId"),
    ExchangeIdContainmentProbe("wire_snake", "wire", "exchange_id"),
    ExchangeIdContainmentProbe("wire_camel", "wire", "exchangeId"),
    ExchangeIdContainmentProbe("correlation_snake", "correlation", "exchange_id"),
    ExchangeIdContainmentProbe("correlation_camel", "correlation", "exchangeId"),
    ExchangeIdContainmentProbe("turn_snake", "turn", "exchange_id"),
    ExchangeIdContainmentProbe("turn_camel", "turn", "exchangeId"),
)


def exchange_id_from_record(record: object) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in EXCHANGE_ID_KEYS:
        exchange_id = _non_empty_string(record.get(key))
        if exchange_id is not None:
            return exchange_id
    for key in EXCHANGE_ID_CONTAINERS:
        exchange_id = exchange_id_from_record(record.get(key))
        if exchange_id is not None:
            return exchange_id
    return None


def exchange_id_containment_sql(column: str) -> str:
    return "\n    OR ".join(
        f"{column} @> %({probe.name})s" for probe in EXCHANGE_ID_CONTAINMENT_PROBES
    )


def exchange_id_containment_params(exchange_id: str) -> dict[str, Jsonb]:
    return {
        probe.name: Jsonb(_exchange_id_pattern(probe=probe, exchange_id=exchange_id))
        for probe in EXCHANGE_ID_CONTAINMENT_PROBES
    }


def _exchange_id_pattern(*, probe: ExchangeIdContainmentProbe, exchange_id: str) -> JsonObject:
    value: JsonObject = {probe.key: exchange_id}
    if probe.container is None:
        return value
    return {probe.container: value}


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
