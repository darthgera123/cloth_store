/** Resolve a public asset path against the deployed base path. */
export function publicAsset(path: string): string {
  if (/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(path) || path.startsWith("data:")) return path;
  return `${import.meta.env.BASE_URL.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}
