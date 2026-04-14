export function displayModel(provider: string, model: string): string {
  const prefix = `${provider}/`;
  return model.startsWith(prefix) ? model.slice(prefix.length) : model;
}
