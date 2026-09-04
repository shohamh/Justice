import { createServer, type Server } from "node:http";
import { once } from "node:events";

import { expect, test } from "@playwright/test";

import { apiRequest } from "./api";

let server: Server;
let baseURL: string;
let receivedAuthorization: string | undefined;
let receivedBody = "";

test.beforeAll(async () => {
  server = createServer(async (request, response) => {
    if (request.url === "/api/auth/refresh") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ access_token: "setup-token" }));
      return;
    }

    if (request.url === "/api/failure") {
      response.writeHead(422, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: "invalid setup" }));
      return;
    }

    for await (const chunk of request) {
      receivedBody += chunk;
    }
    receivedAuthorization = request.headers.authorization;
    response.writeHead(201, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "created" }));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("Test server did not expose a TCP address.");
  }
  baseURL = `http://127.0.0.1:${address.port}`;
});

test.afterAll(async () => {
  server.close();
  await once(server, "close");
});

test("apiRequest refreshes an access token and sends an authenticated JSON setup request", async ({ playwright }) => {
  const request = await playwright.request.newContext({ baseURL });

  try {
    const response = await apiRequest(request, "POST", "/api/setup", { name: "e2e" });

    expect(response.status()).toBe(201);
    expect(receivedAuthorization).toBe("Bearer setup-token");
    expect(receivedBody).toBe('{"name":"e2e"}');
  } finally {
    await request.dispose();
  }
});

test("apiRequest includes the response body when setup fails", async ({ playwright }) => {
  const request = await playwright.request.newContext({ baseURL });

  try {
    await expect(apiRequest(request, "POST", "/api/failure")).rejects.toThrow(
      "POST /api/failure failed with 422: {\"detail\":\"invalid setup\"}",
    );
  } finally {
    await request.dispose();
  }
});
