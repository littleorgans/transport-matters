import type { ComponentProps } from "react";
import { buildExchangeTrackTree } from "../../hooks/useExchanges";
import type { ExchangeTrackStub } from "../../types";
import { ExchangeList } from "../ExchangeList";

type ExchangeListWithTrackTreeProps = Omit<ComponentProps<typeof ExchangeList>, "trackTree"> & {
  trackStubs?: ExchangeTrackStub[];
};

export function ExchangeListWithTrackTree({
  exchanges,
  trackStubs = [],
  ...props
}: ExchangeListWithTrackTreeProps) {
  return (
    <ExchangeList
      {...props}
      exchanges={exchanges}
      trackTree={buildExchangeTrackTree(exchanges, trackStubs)}
    />
  );
}
