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

export function wsUrl(path: string): string {
  const base = getBackendOrigin();
  if (!base) {
    if (typeof window === "undefined") return path;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${path}`;
  }
  return base.replace(/^http:/, "ws:").replace(/^https:/, "wss:") + path;
}
