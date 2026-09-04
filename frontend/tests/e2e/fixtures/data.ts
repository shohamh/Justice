import type { APIRequestContext, APIResponse } from "@playwright/test";

export interface ScenarioData {
  runId: string;
  dutyType: ScenarioResource;
  location: ScenarioResource;
  exemptionType: ScenarioResource;
}

export interface ScenarioResource extends Record<string, unknown> {
  id: string;
  name: string;
}

const runId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
let sequence = 0;

export function createUniqueName(prefix: string): string {
  const normalizedPrefix = prefix.trim().replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!normalizedPrefix) {
    throw new Error("createUniqueName requires a non-empty prefix.");
  }

  sequence += 1;
  return `${normalizedPrefix}-${runId}-${sequence}`;
}

async function responseData(response: APIResponse, resource: string): Promise<ScenarioResource> {
  if (!response.ok()) {
    throw new Error(`Could not create ${resource}: ${response.status()} ${await response.text()}`);
  }

  const data: unknown = await response.json();
  if (
    typeof data !== "object" || data === null ||
    typeof (data as { id?: unknown }).id !== "string" ||
    typeof (data as { name?: unknown }).name !== "string"
  ) {
    throw new Error(`Could not create ${resource}: response did not include an id and name.`);
  }

  return data as ScenarioResource;
}

async function refreshAccessToken(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/auth/refresh");
  if (!response.ok()) {
    throw new Error(`Could not refresh the scenario setup session: ${response.status()} ${await response.text()}`);
  }

  const data: unknown = await response.json();
  if (typeof data !== "object" || data === null || typeof (data as { access_token?: unknown }).access_token !== "string") {
    throw new Error("Could not refresh the scenario setup session: response did not include an access token.");
  }

  return (data as { access_token: string }).access_token;
}

export async function createScenarioData(request: APIRequestContext): Promise<ScenarioData> {
  const scenarioId = createUniqueName("e2e");
  const headers = { Authorization: `Bearer ${await refreshAccessToken(request)}` };
  const dutyTypeName = `duty-${scenarioId}`;
  const locationName = `location-${scenarioId}`;
  const exemptionTypeName = `exemption-${scenarioId}`;

  const [dutyTypeResponse, locationResponse, exemptionTypeResponse] = await Promise.all([
    request.post("/api/duty-config/duty-types", {
      data: { name: dutyTypeName, score_per_day: "1.00", is_external: false },
      headers,
    }),
    request.post("/api/duty-config/locations", {
      data: { name: locationName },
      headers,
    }),
    request.post("/api/duty-config/exemption-types", {
      data: { name: exemptionTypeName },
      headers,
    }),
  ]);

  const [dutyType, location, exemptionType] = await Promise.all([
    responseData(dutyTypeResponse, "duty type"),
    responseData(locationResponse, "location"),
    responseData(exemptionTypeResponse, "exemption type"),
  ]);

  return { runId: scenarioId, dutyType, location, exemptionType };
}
