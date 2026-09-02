import type { APIRequestContext, APIResponse } from "@playwright/test";

type JsonBody = Record<string, unknown> | undefined;

async function responseError(response: APIResponse, method: string, path: string): Promise<Error> {
  const body = await response.text();
  return new Error(`${method} ${path} failed with ${response.status()}: ${body || "<empty response body>"}`);
}

export async function apiRequest(
  request: APIRequestContext,
  method: string,
  path: string,
  body?: JsonBody,
): Promise<APIResponse> {
  const refresh = await request.post("/api/auth/refresh");
  if (!refresh.ok()) throw await responseError(refresh, "POST", "/api/auth/refresh");

  const payload = (await refresh.json()) as { access_token?: unknown };
  if (typeof payload.access_token !== "string" || payload.access_token.length === 0) {
    throw new Error("POST /api/auth/refresh returned no access_token");
  }

  const response = await request.fetch(path, {
    method,
    headers: { Authorization: `Bearer ${payload.access_token}`, "Content-Type": "application/json" },
    data: body,
  });
  if (!response.ok()) throw await responseError(response, method, path);
  return response;
}
