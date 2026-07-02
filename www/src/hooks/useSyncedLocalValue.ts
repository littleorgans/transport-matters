import { type Dispatch, type SetStateAction, useEffect, useState } from "react";

export function useSyncedLocalValue<TValue>(
  value: TValue,
): [TValue, Dispatch<SetStateAction<TValue>>] {
  const [localValue, setLocalValue] = useState(value);
  useEffect(() => {
    setLocalValue(value);
  }, [value]);
  return [localValue, setLocalValue];
}
