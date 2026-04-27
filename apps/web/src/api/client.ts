// Typed API client — will be implemented in T02/T06.
// See 05-api-spec.md for endpoint contracts.

const BASE = "/api";

export async function healthCheck(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}
