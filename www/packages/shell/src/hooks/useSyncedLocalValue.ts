import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

export function useSyncedLocalValue<TValue>(
  value: TValue,
  syncKey: unknown = value,
): [TValue, Dispatch<SetStateAction<TValue>>] {
  const [localValue, setLocalValue] = useState(value);
  useEffect(() => {
    void syncKey;
    setLocalValue(value);
  }, [value, syncKey]);
  return [localValue, setLocalValue];
}
