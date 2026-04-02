import { QueryClient } from "@tanstack/react-query";

// RT Viewer API base — points to the FastAPI backend on port 8000
export const API_BASE =
  "__PORT_8000__".startsWith("__")
    ? "http://127.0.0.1:8000"   // 127.0.0.1 avoids IPv6/IPv4 mismatch on Windows
    : "__PORT_8000__";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
    },
  },
});

export async function apiRequest(
  method: string,
  url: string,
  body?: unknown
): Promise<Response> {
  const res = await fetch(`${API_BASE}${url}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`${method} ${url} failed: ${res.status} — ${text}`);
  }
  return res;
}
