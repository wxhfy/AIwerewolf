const rawBackendOrigin = process.env.NEXT_PUBLIC_BACKEND_ORIGIN || "";

function normalizeOrigin(origin: string): string {
  return origin.replace(/\/+$/, "");
}

export function getBackendOrigin(): string {
  if (rawBackendOrigin) {
    return normalizeOrigin(rawBackendOrigin);
  }
  if (typeof window !== "undefined") {
    return normalizeOrigin(window.location.origin);
  }
  return "";
}

export function apiUrl(path: string): string {
  const base = getBackendOrigin();
  return `${base}${path}`;
}
