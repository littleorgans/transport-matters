export const exchangesPrefix = ["exchanges"] as const;

export function exchangesKey(includeHistory: boolean): readonly ["exchanges", boolean] {
  return ["exchanges", includeHistory];
}

export function exchangeKey(id: string): readonly ["exchange", string] {
  return ["exchange", id];
}

export function turnContentKey(id: string): readonly ["turn-content", string] {
  return ["turn-content", id];
}
