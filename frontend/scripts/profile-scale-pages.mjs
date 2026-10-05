#!/usr/bin/env node

import { link, mkdir, open, rename, unlink } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import process from "node:process";
import { chromium } from "playwright";

const RUNS = parsePositiveInteger(process.env.JUSTICE_SCALE_RUNS ?? "5", "JUSTICE_SCALE_RUNS");
const CONCURRENCY = parseConcurrency(process.argv.slice(2), process.env.JUSTICE_SCALE_CONCURRENCY);
const BASE_URL = parseLocalBaseUrl(process.env.JUSTICE_SCALE_BASE_URL);
const USERNAME = process.env.JUSTICE_SCALE_ADMIN_USERNAME;
const PASSWORD = process.env.JUSTICE_SCALE_ADMIN_PASSWORD;
const SOLDIER_PERSONAL_NUMBER = process.env.JUSTICE_SCALE_SOLDIER_PERSONAL_NUMBER?.trim() || "SCALE20-00001";
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const RUN_STARTED_AT = new Date().toISOString();
const RUN_ID = `${new Date().toISOString().replace(/[-:.]/g, "")}-${process.pid}-${randomUUID().slice(0, 8)}`;
const DEFAULT_OUTPUT_PATH = resolve(
  REPO_ROOT,
  "docs/benchmarks/data",
  `scale-20k-pages-run-${RUN_ID}.json`,
);
const requestedOutputPath = process.env.JUSTICE_SCALE_OUTPUT;
const OUTPUT_PATH = requestedOutputPath
  ? (isAbsolute(requestedOutputPath)
      ? resolve(requestedOutputPath)
      : resolve(REPO_ROOT, requestedOutputPath))
  : DEFAULT_OUTPUT_PATH;
const TEMP_OUTPUT_PATH = `${OUTPUT_PATH}.${RUN_ID}.tmp`;
const TIMEOUT_MS = parseBoundedInteger(
  process.env.JUSTICE_SCALE_TIMEOUT_MS ?? "600000",
  "JUSTICE_SCALE_TIMEOUT_MS",
  1_000,
  3_600_000,
);
const NAVIGATION_TIMEOUT_MS = TIMEOUT_MS;
const QUIET_TIMEOUT_MS = TIMEOUT_MS;

if (!USERNAME || !PASSWORD) {
  throw new Error("Set JUSTICE_SCALE_ADMIN_USERNAME and JUSTICE_SCALE_ADMIN_PASSWORD.");
}

const scenarios = [
  {
    id: "hr-sync-review",
    path: "/admin/settings?tab=6",
    readiness: ['[data-testid="hr-sync-review-content"]'],
    mode: "navigation",
  },
  {
    id: "transparency-whole-organization",
    path: "/transparency",
    readiness: ['[data-testid="transparency-page"]'],
    mode: "navigation",
  },
  {
    id: "hierarchy-whole-organization",
    path: "/team",
    readiness: ['[data-testid="team-page"]', '[data-testid="soldier-table"]'],
    mode: "navigation",
  },
  {
    id: "soldier-detail",
    path: "/team",
    readiness: ['[data-testid="team-page"]'],
    mode: "soldier-detail",
  },
  {
    id: "calendar-whole-organization",
    path: "/unit-calendar",
    readiness: ['[data-testid="unit-calendar-page"]', '[data-testid="fullcalendar"]'],
    mode: "navigation",
  },
  {
    id: "calendar-synthetic-team",
    path: "/unit-calendar",
    readiness: ['[data-testid="unit-calendar-page"]', '[data-testid="fullcalendar"]'],
    mode: "calendar-team",
  },
  {
    id: "home-dashboard",
    path: "/",
    readiness: ['[data-testid="personal-data-panel"]', '[data-testid="panel-alerts"]'],
    mode: "navigation",
  },
];
const scenarioFilter = process.env.JUSTICE_SCALE_SCENARIOS
  ?.split(",")
  .map((id) => id.trim())
  .filter(Boolean);
const selectedScenarios = scenarioFilter?.length
  ? scenarios.filter(({ id }) => scenarioFilter.includes(id))
  : scenarios;
if (scenarioFilter?.length && selectedScenarios.length !== new Set(scenarioFilter).size) {
  throw new Error("JUSTICE_SCALE_SCENARIOS contains an unknown scenario id.");
}

const measurements = [];
let browserVersion = null;
let outputReady = false;
let outputWriteQueue = Promise.resolve();

class ArtifactWriteError extends Error {
  constructor(cause) {
    super("Failed to persist the scale-profile artifact.");
    this.name = "ArtifactWriteError";
    this.cause = cause;
  }
}

class OutputCollisionError extends Error {
  constructor(path) {
    super(`Refusing to overwrite benchmark output: ${path}. Choose a new JUSTICE_SCALE_OUTPUT.`);
    this.name = "OutputCollisionError";
  }
}

function buildOutput() {
  return {
    schemaVersion: 2,
    runId: RUN_ID,
    generatedAtUtc: RUN_STARTED_AT,
    startedAtUtc: RUN_STARTED_AT,
    updatedAtUtc: new Date().toISOString(),
    browser: { engine: "chromium", version: browserVersion },
    runsPerScenario: RUNS,
    batchesPerScenario: RUNS,
    concurrency: CONCURRENCY,
    clientsPerBatch: CONCURRENCY,
    startBarrier: "all clients begin each cold/warm measurement together",
    authenticationSetup: "one login per invocation; independent client contexts restore from copied refresh-cookie storageState",
    summaryCoverage: "per-run response-byte and database totals require values for every tracked API request",
    serverTiming: "x-scale-server-ms measures ASGI time through response-start; serverMinusDbMs is the signed wall-minus-accumulated-SQL residual, not CPU-only time",
    renderTiming: "firstContentfulPaintMs comes from the browser Paint Timing API and is relative to a document navigation that occurs during the measured journey; it is null for in-document interactions without a new navigation; pageReadyMs is measured separately through the configured readiness marker and API quiet period",
    timeoutMs: TIMEOUT_MS,
    scenarios: selectedScenarios.map(({ id, path, mode }) => ({
      id,
      route: safeEndpoint("GET", routeUrl(path)).replace(/^GET /, ""),
      workload: mode,
    })),
    hrProviderSync: "not-invoked",
    measurements,
    summaries: summarizeMeasurements(measurements),
  };
}

async function prepareOutput() {
  try {
    await mkdir(dirname(OUTPUT_PATH), { recursive: true });
  } catch (error) {
    throw new ArtifactWriteError(error);
  }

  const data = snapshotBuffer();
  let temporaryHandle = null;
  let temporaryCreated = false;
  try {
    temporaryHandle = await open(TEMP_OUTPUT_PATH, "wx");
    temporaryCreated = true;
    await writeBuffer(temporaryHandle, data);
    await temporaryHandle.close();
    temporaryHandle = null;
    try {
      await link(TEMP_OUTPUT_PATH, OUTPUT_PATH);
    } catch (error) {
      if (error?.code === "EEXIST") throw new OutputCollisionError(OUTPUT_PATH);
      throw new ArtifactWriteError(error);
    }
    await unlink(TEMP_OUTPUT_PATH);
    temporaryCreated = false;
    outputReady = true;
  } catch (error) {
    if (temporaryHandle) await temporaryHandle.close().catch(() => {});
    if (temporaryCreated) await unlink(TEMP_OUTPUT_PATH).catch(() => {});
    if (error instanceof OutputCollisionError || error instanceof ArtifactWriteError) throw error;
    throw new ArtifactWriteError(error);
  }
}

function snapshotBuffer() {
  try {
    return Buffer.from(`${JSON.stringify(buildOutput(), null, 2)}\n`, "utf8");
  } catch (error) {
    throw new ArtifactWriteError(error);
  }
}

async function writeBuffer(handle, data) {
  let offset = 0;
  while (offset < data.length) {
    const { bytesWritten } = await handle.write(data, offset, data.length - offset, offset);
    if (bytesWritten === 0) throw new Error("Could not finish writing benchmark output.");
    offset += bytesWritten;
  }
  await handle.sync();
}

function persistOutput() {
  if (!outputReady) throw new ArtifactWriteError(new Error("Benchmark output was not prepared."));
  const data = snapshotBuffer();
  const write = outputWriteQueue.then(async () => {
    let temporaryHandle = null;
    let temporaryCreated = false;
    try {
      temporaryHandle = await open(TEMP_OUTPUT_PATH, "wx");
      temporaryCreated = true;
      await writeBuffer(temporaryHandle, data);
      await temporaryHandle.close();
      temporaryHandle = null;
      await rename(TEMP_OUTPUT_PATH, OUTPUT_PATH);
      temporaryCreated = false;
    } catch (error) {
      if (temporaryHandle) await temporaryHandle.close().catch(() => {});
      if (temporaryCreated) await unlink(TEMP_OUTPUT_PATH).catch(() => {});
      throw new ArtifactWriteError(error);
    }
  });
  outputWriteQueue = write.catch(() => {});
  return write;
}

function parsePositiveInteger(raw, label) {
  return parseBoundedInteger(raw, label, 1, 50);
}

function parseConcurrency(args, environmentValue) {
  let cliValue;
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] !== "--concurrency" || cliValue !== undefined || index + 1 >= args.length) {
      throw new Error("Usage: node frontend/scripts/profile-scale-pages.mjs [--concurrency 1|5|10].");
    }
    cliValue = args[index + 1];
    index += 1;
  }

  const value = cliValue ?? environmentValue ?? "1";
  if (!["1", "5", "10"].includes(value)) {
    throw new Error("--concurrency (or JUSTICE_SCALE_CONCURRENCY) must be 1, 5, or 10.");
  }
  return Number(value);
}

function parseBoundedInteger(raw, label, minimum, maximum) {
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${label} must be an integer between ${minimum} and ${maximum}.`);
  }
  return parsed;
}

function parseLocalBaseUrl(raw) {
  if (!raw) throw new Error("Set JUSTICE_SCALE_BASE_URL to the local frontend URL.");

  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("JUSTICE_SCALE_BASE_URL must be a valid local HTTP(S) URL.");
  }
  if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password || !isLoopback(parsed.hostname)) {
    throw new Error("JUSTICE_SCALE_BASE_URL must use local HTTP(S) without URL credentials.");
  }

  // Never propagate arbitrary query or fragment data into route records.
  parsed.search = "";
  parsed.hash = "";
  return parsed;
}

function isLoopback(hostname) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return host === "localhost" || host.endsWith(".localhost") || host === "127.0.0.1" || host === "::1";
}

function routeUrl(path) {
  return new URL(path, BASE_URL).toString();
}

function safeEndpoint(method, rawUrl) {
  let pathname = "/unknown";
  try {
    const parsed = new URL(rawUrl);
    pathname = parsed.pathname
      .replace(/\/SCALE20-[^/]+/gi, "/:synthetic-id")
      .replace(/\/[0-9]{5,}(?=\/|$)/g, "/:id")
      .replace(/\/[0-9a-f]{8}-[0-9a-f-]{27,}(?=\/|$)/gi, "/:id");
  } catch {
    // A fixed placeholder is safer than persisting an unparseable URL.
  }
  return `${String(method).toUpperCase()} ${pathname}`;
}

function apiOriginAllowlist() {
  const origins = new Set([BASE_URL.origin]);
  const optionalApiOrigin = process.env.JUSTICE_SCALE_API_ORIGIN;
  if (optionalApiOrigin) {
    let parsed;
    try {
      parsed = new URL(optionalApiOrigin);
    } catch {
      throw new Error("JUSTICE_SCALE_API_ORIGIN must be a local HTTP(S) origin.");
    }
    if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password || !isLoopback(parsed.hostname)) {
      throw new Error("JUSTICE_SCALE_API_ORIGIN must be local HTTP(S) without URL credentials.");
    }
    origins.add(parsed.origin);
  }
  return origins;
}

const API_ORIGINS = apiOriginAllowlist();

function isTrackedApiRequest(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return API_ORIGINS.has(parsed.origin) && /^\/api(?:\/|$)/.test(parsed.pathname);
  } catch {
    return false;
  }
}

function safeErrorName(name) {
  return typeof name === "string" && /^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(name) ? name : "Error";
}

function newMeasurement(scenario, run, client, batch, mode) {
  return {
    scenario: scenario.id,
    attempt: run,
    run,
    batch,
    client,
    concurrency: CONCURRENCY,
    mode,
    pageReadyMs: null,
    firstContentfulPaintMs: null,
    selectorVisibleMs: null,
    apiQuietMs: null,
    readiness: "pending",
    phaseTimings: {},
    apiRequestCount: 0,
    apiResponses: [],
    consoleErrors: { count: 0, types: [] },
    pageErrors: { count: 0, names: [] },
    longTasksOver50Ms: { count: 0, totalMs: 0, maxMs: 0 },
  };
}

function attachPageObservers(page, collector) {
  const requestStarts = new WeakMap();
  const requestResponses = new WeakMap();
  collector.pending ??= new Set();
  collector.activeApiRequests ??= new Set();
  collector.lastApiActivityAt = performance.now();

  page.on("request", (request) => {
    if (isTrackedApiRequest(request.url())) {
      requestStarts.set(request, performance.now());
      collector.activeApiRequests.add(request);
      collector.lastApiActivityAt = performance.now();
    }
  });

  page.on("response", (response) => {
    const request = response.request();
    if (requestStarts.has(request)) requestResponses.set(request, response);
  });

  page.on("requestfinished", (request) => {
    const startedAt = requestStarts.get(request);
    const response = requestResponses.get(request);
    if (startedAt === undefined) return;
    requestStarts.delete(request);
    requestResponses.delete(request);
    collector.activeApiRequests.delete(request);
    collector.lastApiActivityAt = performance.now();
    if (!response) return;

    const measurement = collector.current;
    if (!measurement) return;
    const finishedAt = performance.now();
    const headers = response.headers();
    const contentLength = parseOptionalByteCount(headers["content-length"]);
    const dbQueryCount = parseOptionalByteCount(headers["x-scale-db-queries"]);
    const dbMs = parseOptionalNumber(headers["x-scale-db-ms"]);
    const serverMs = parseOptionalNumber(headers["x-scale-server-ms"]);
    measurement.apiResponses.push({
      method: request.method().toUpperCase(),
      endpoint: safeEndpoint(request.method(), request.url()),
      status: response.status(),
      durationMs: roundMillis(finishedAt - startedAt),
      responseBytes: contentLength,
      dbQueryCount,
      dbMs,
      serverMs,
      serverMinusDbMs: Number.isFinite(serverMs) && Number.isFinite(dbMs) ? roundMillis(serverMs - dbMs) : null,
    });
    measurement.apiRequestCount = measurement.apiResponses.length;
  });

  page.on("requestfailed", (request) => {
    const startedAt = requestStarts.get(request);
    if (startedAt === undefined) return;
    requestStarts.delete(request);
    requestResponses.delete(request);
    collector.activeApiRequests.delete(request);
    collector.lastApiActivityAt = performance.now();
    const measurement = collector.current;
    if (!measurement) return;
    measurement.apiResponses.push({
      method: request.method().toUpperCase(),
      endpoint: safeEndpoint(request.method(), request.url()),
      status: null,
      durationMs: roundMillis(performance.now() - startedAt),
      responseBytes: null,
      dbQueryCount: null,
      dbMs: null,
      serverMs: null,
      serverMinusDbMs: null,
      failed: true,
    });
    measurement.apiRequestCount = measurement.apiResponses.length;
  });

  page.on("console", (message) => {
    if (message.type() !== "error" || !collector.current) return;
    const errors = collector.current.consoleErrors;
    errors.count += 1;
    errors.types = [...new Set([...errors.types, message.type()])].sort();
  });

  page.on("pageerror", (error) => {
    if (!collector.current) return;
    const errors = collector.current.pageErrors;
    errors.count += 1;
    errors.names = [...new Set([...errors.names, safeErrorName(error?.name)])].sort();
  });
}

function parseOptionalByteCount(raw) {
  if (raw === undefined) return null;
  const value = Number.parseInt(raw, 10);
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function parseOptionalNumber(raw) {
  if (raw === undefined) return null;
  const value = Number.parseFloat(raw);
  return Number.isFinite(value) && value >= 0 ? roundMillis(value) : null;
}

function safeFailureCategory(error) {
  const message = String(error?.message ?? "").toLowerCase();
  if (message.includes("waiting for api requests")) return "api-quiescence-timeout";
  if (message.includes("waiting for locator") || message.includes("waiting for selector")) {
    return "locator-timeout";
  }
  if (error?.name === "TimeoutError") return "timeout";
  return "runtime-error";
}

function roundMillis(value) {
  return Math.round(value * 100) / 100;
}

function percentileSummary(rawValues) {
  const values = rawValues.filter(Number.isFinite).sort((left, right) => left - right);
  if (!values.length) return { sampleCount: 0, p50: null, p95: null };
  const nearestRank = (percentile) => values[Math.max(0, Math.ceil(percentile * values.length) - 1)];
  return {
    sampleCount: values.length,
    p50: roundMillis(nearestRank(0.5)),
    p95: roundMillis(nearestRank(0.95)),
  };
}

function sumIfComplete(rows, key) {
  if (!rows.length) return null;
  const values = rows.map((row) => row[key]).filter(Number.isFinite);
  return values.length === rows.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

function summarizeMeasurements(rows) {
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify([row.scenario, row.mode, row.concurrency]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }

  return [...groups.values()].map((group) => {
    const { scenario, mode, concurrency } = group[0];
    const ready = group.filter((measurement) => measurement.readiness === "ready");
    const phaseNames = [...new Set(ready.flatMap((measurement) => Object.keys(measurement.phaseTimings)))].sort();
    const endpointGroups = new Map();
    for (const measurement of group) {
      for (const response of measurement.apiResponses) {
        const key = JSON.stringify([response.method, response.endpoint]);
        if (!endpointGroups.has(key)) endpointGroups.set(key, []);
        endpointGroups.get(key).push(response);
      }
    }

    const perMeasurement = (selector) => group.map(selector).filter(Number.isFinite);
    const perReadyMeasurement = (selector) => ready.map(selector).filter(Number.isFinite);
    return {
      scenario,
      mode,
      concurrency,
      sampleCount: group.length,
      readyCount: ready.length,
      failedCount: group.length - ready.length,
      metrics: {
        pageReadyMs: percentileSummary(perReadyMeasurement((measurement) => measurement.pageReadyMs)),
        firstContentfulPaintMs: percentileSummary(perReadyMeasurement((measurement) => measurement.firstContentfulPaintMs)),
        selectorVisibleMs: percentileSummary(perMeasurement((measurement) => measurement.selectorVisibleMs)),
        apiQuietMs: percentileSummary(perMeasurement((measurement) => measurement.apiQuietMs)),
        apiRequestCount: percentileSummary(perMeasurement((measurement) => measurement.apiRequestCount)),
        totalApiDurationMs: percentileSummary(perMeasurement((measurement) => sumIfComplete(measurement.apiResponses, "durationMs"))),
        totalResponseBytes: percentileSummary(perMeasurement((measurement) => sumIfComplete(measurement.apiResponses, "responseBytes"))),
        totalDbQueryCount: percentileSummary(perMeasurement((measurement) => sumIfComplete(measurement.apiResponses, "dbQueryCount"))),
        totalDbMs: percentileSummary(perMeasurement((measurement) => sumIfComplete(measurement.apiResponses, "dbMs"))),
        totalServerMs: percentileSummary(perMeasurement((measurement) => sumIfComplete(measurement.apiResponses, "serverMs"))),
        totalServerMinusDbMs: percentileSummary(perMeasurement((measurement) => sumIfComplete(measurement.apiResponses, "serverMinusDbMs"))),
        longTaskCount: percentileSummary(perMeasurement((measurement) => measurement.longTasksOver50Ms.count)),
        longTaskTotalMs: percentileSummary(perMeasurement((measurement) => measurement.longTasksOver50Ms.totalMs)),
        longTaskMaxMs: percentileSummary(perMeasurement((measurement) => measurement.longTasksOver50Ms.maxMs)),
        phaseTimingsMs: Object.fromEntries(phaseNames.map((name) => [
          name,
          percentileSummary(perReadyMeasurement((measurement) => measurement.phaseTimings[name])),
        ])),
      },
      apiEndpoints: [...endpointGroups.entries()].map(([key, responses]) => {
        const [method, endpoint] = JSON.parse(key);
        return {
          method,
          endpoint,
          statusCounts: responses.reduce((counts, response) => {
            const status = response.status === null ? "failed" : String(response.status);
            counts[status] = (counts[status] ?? 0) + 1;
            return counts;
          }, {}),
          durationMs: percentileSummary(responses.map((response) => response.durationMs)),
          responseBytes: percentileSummary(responses.map((response) => response.responseBytes)),
          dbQueryCount: percentileSummary(responses.map((response) => response.dbQueryCount)),
          dbMs: percentileSummary(responses.map((response) => response.dbMs)),
          serverMs: percentileSummary(responses.map((response) => response.serverMs)),
          serverMinusDbMs: percentileSummary(responses.map((response) => response.serverMinusDbMs)),
        };
      }).sort((left, right) => left.endpoint.localeCompare(right.endpoint) || left.method.localeCompare(right.method)),
    };
  }).sort((left, right) => left.scenario.localeCompare(right.scenario)
    || left.mode.localeCompare(right.mode)
    || left.concurrency - right.concurrency);
}

function createBarrier(parties) {
  let arrivals = [];
  return (value = undefined) => new Promise((resolvePromise) => {
    arrivals.push({ resolve: resolvePromise, value });
    if (arrivals.length === parties) {
      const released = arrivals;
      arrivals = [];
      const values = released.map(({ value: arrivalValue }) => arrivalValue);
      released.forEach(({ resolve: release }) => release(values));
    }
  });
}

async function waitForApiQuiescence(collector) {
  const deadline = performance.now() + QUIET_TIMEOUT_MS;
  while (true) {
    await Promise.all([...collector.pending]);
    const quietForMs = performance.now() - collector.lastApiActivityAt;
    if (
      collector.activeApiRequests.size === 0 &&
      collector.pending.size === 0 &&
      quietForMs >= 500
    ) {
      return;
    }
    if (performance.now() >= deadline) {
      const error = new Error("Timed out waiting for API requests to settle.");
      error.name = "TimeoutError";
      throw error;
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
  }
}

function recordMeasurementMilestone(collector, field) {
  if (collector.current && Number.isFinite(collector.measurementStartedAt)) {
    collector.current[field] = roundMillis(performance.now() - collector.measurementStartedAt);
  }
}

async function waitForReadiness(page, selectors, collector) {
  for (const selector of selectors) {
    await page.locator(selector).waitFor({ state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  }
  recordMeasurementMilestone(collector, "selectorVisibleMs");
  await waitForApiQuiescence(collector);
  recordMeasurementMilestone(collector, "apiQuietMs");
}

async function readLongTaskDelta(page, baseline) {
  return page.evaluate((documentBaseline) => {
    const durations = window.__justiceScaleLongTasks ?? [];
    const sameDocument = documentBaseline.timeOrigin === performance.timeOrigin;
    const measured = durations.slice(sameDocument ? documentBaseline.length : 0).filter((duration) => duration > 50);
    return {
      count: measured.length,
      totalMs: measured.reduce((sum, duration) => sum + duration, 0),
      maxMs: measured.length ? Math.max(...measured) : 0,
    };
  }, baseline).catch(() => ({ count: 0, totalMs: 0, maxMs: 0 }));
}

async function readDocumentPaintTiming(page) {
  return page.evaluate(() => {
    const entry = performance.getEntriesByType("paint")
      .find((candidate) => candidate.name === "first-contentful-paint");
    return {
      timeOrigin: performance.timeOrigin,
      firstContentfulPaintMs: Number.isFinite(entry?.startTime) ? entry.startTime : null,
    };
  }).catch(() => ({ timeOrigin: null, firstContentfulPaintMs: null }));
}

async function longTaskBaseline(page) {
  return page.evaluate(() => ({
    timeOrigin: performance.timeOrigin,
    length: (window.__justiceScaleLongTasks ?? []).length,
  })).catch(() => ({ timeOrigin: null, length: 0 }));
}

async function recordMeasurement(page, collector, scenario, run, client, batch, mode, action) {
  const measurement = newMeasurement(scenario, run, client, batch, mode);
  const baseline = await longTaskBaseline(page);
  const documentTimeOriginBefore = (await readDocumentPaintTiming(page)).timeOrigin;
  const startedAt = performance.now();
  collector.current = measurement;
  collector.measurementStartedAt = startedAt;

  try {
    const phaseTimings = await action();
    if (phaseTimings && typeof phaseTimings === "object") {
      measurement.phaseTimings = phaseTimings;
    }
    const paintTiming = await readDocumentPaintTiming(page);
    if (
      paintTiming.timeOrigin !== documentTimeOriginBefore &&
      Number.isFinite(paintTiming.firstContentfulPaintMs)
    ) {
      measurement.firstContentfulPaintMs = paintTiming.firstContentfulPaintMs;
    }
    await waitForApiQuiescence(collector);
    measurement.pageReadyMs = roundMillis(performance.now() - startedAt);
    measurement.readiness = "ready";
  } catch (error) {
    measurement.pageReadyMs = roundMillis(performance.now() - startedAt);
    measurement.readiness = "failed";
    measurement.failure = {
      stage: "page-ready",
      errorName: safeErrorName(error?.name),
      category: safeFailureCategory(error),
    };
  } finally {
    const longTasks = await readLongTaskDelta(page, baseline);
    measurement.longTasksOver50Ms = {
      count: longTasks.count,
      totalMs: roundMillis(longTasks.totalMs),
      maxMs: roundMillis(longTasks.maxMs),
    };
    collector.current = null;
    collector.measurementStartedAt = null;
  }

  measurements.push(measurement);
  await persistOutput();
  process.stdout.write(
    `${scenario.id} concurrency=${CONCURRENCY} batch=${batch} client=${client} ${mode} ${measurement.readiness} ${measurement.pageReadyMs ?? "-"}ms\n`,
  );
}

async function login(page) {
  await page.goto(routeUrl("/login"), { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
  await page.locator('[data-testid="login-form"]').waitFor({ state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  await page.locator('[data-testid="personal-number-input"]').fill(USERNAME);
  await page.locator('[data-testid="password-input"]').fill(PASSWORD);
  await page.locator('[data-testid="login-submit"]').click();
  await page.waitForFunction(() => window.location.pathname !== "/login", null, { timeout: NAVIGATION_TIMEOUT_MS });
}

async function authenticateStorageState(browser) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  try {
    const page = await context.newPage();
    await login(page);
    const storageState = await context.storageState();
    const hasRefreshCookie = storageState.cookies.some((cookie) =>
      cookie.name === "refresh_token" && cookie.path === "/api/auth");
    if (!hasRefreshCookie) {
      throw new Error("Scale-profile login did not create the expected refresh cookie.");
    }
    return storageState;
  } finally {
    await context.close();
  }
}

async function navigateAndWait(page, scenario, collector) {
  await page.goto(routeUrl(scenario.path), { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
  await waitForReadiness(page, scenario.readiness, collector);
}

async function syntheticSoldierEditButton(page) {
  const table = page.getByTestId("soldier-table");
  await table.locator("input").first().fill(SOLDIER_PERSONAL_NUMBER);
  const button = page.getByTestId(`edit-${SOLDIER_PERSONAL_NUMBER}`);
  await button.waitFor({ state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  return button;
}

async function openSyntheticSoldier(page, scenario, collector) {
  const teamPageStartedAt = performance.now();
  await navigateAndWait(page, scenario, collector);
  const teamPageReadyMs = roundMillis(performance.now() - teamPageStartedAt);

  const filterStartedAt = performance.now();
  const editButton = await syntheticSoldierEditButton(page);
  const syntheticSoldierFilterMs = roundMillis(performance.now() - filterStartedAt);

  const detailStartedAt = performance.now();
  await editButton.click();
  await page.locator('[data-testid="unified-soldier-modal"]').waitFor({ state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  recordMeasurementMilestone(collector, "selectorVisibleMs");
  await waitForApiQuiescence(collector);
  recordMeasurementMilestone(collector, "apiQuietMs");
  return {
    teamPageReadyMs,
    syntheticSoldierFilterMs,
    soldierModalReadyMs: roundMillis(performance.now() - detailStartedAt),
  };
}

async function reopenSyntheticSoldier(page, collector) {
  const detailStartedAt = performance.now();
  await page.locator('[data-testid="modal-close"]').click();
  await page.locator('[data-testid="unified-soldier-modal"]').waitFor({ state: "detached", timeout: NAVIGATION_TIMEOUT_MS });
  const editButton = await syntheticSoldierEditButton(page);
  await editButton.click();
  await page.locator('[data-testid="unified-soldier-modal"]').waitFor({ state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  recordMeasurementMilestone(collector, "selectorVisibleMs");
  await waitForApiQuiescence(collector);
  recordMeasurementMilestone(collector, "apiQuietMs");
  return {
    soldierModalReopenMs: roundMillis(performance.now() - detailStartedAt),
  };
}

async function chooseSyntheticTeam(page, collector) {
  const combo = page.getByRole("combobox").first();
  await combo.click();
  await combo.fill("SCALE20 Team");
  const syntheticOption = page.getByRole("option").filter({ hasText: "SCALE20 Team" }).first();
  await syntheticOption.waitFor({ state: "visible", timeout: NAVIGATION_TIMEOUT_MS });
  const selectedOptionId = await syntheticOption.getAttribute("id");
  const selectedPath = (await syntheticOption.innerText()).trim();
  const selectedNodeId = selectedOptionId?.replace(/^unit-calendar-node-option-/, "");
  if (!selectedNodeId || selectedNodeId === selectedOptionId || !selectedPath) {
    throw new Error("The synthetic team hierarchy option did not expose its selected node identity and path.");
  }
  const teamShiftsResponse = page.waitForResponse((response) => {
    if (response.request().method() !== "GET") return false;
    const url = new URL(response.url());
    return url.pathname.endsWith("/api/calendar/shifts") && url.searchParams.get("node_id") === selectedNodeId;
  }, { timeout: NAVIGATION_TIMEOUT_MS }).then(
    (response) => ({ response }),
    (error) => ({ error }),
  );
  await syntheticOption.click();
  await page.waitForFunction(
    (expectedPath) => document.querySelector("#unit-calendar-node-search")?.value === expectedPath,
    selectedPath,
    { timeout: NAVIGATION_TIMEOUT_MS },
  );
  recordMeasurementMilestone(collector, "selectorVisibleMs");
  const teamShiftsResult = await teamShiftsResponse;
  if (teamShiftsResult.error) throw teamShiftsResult.error;
  await waitForApiQuiescence(collector);
  recordMeasurementMilestone(collector, "apiQuietMs");
}

async function createProfiledPage(browser, storageState) {
  const context = await browser.newContext({
    storageState: structuredClone(storageState),
    serviceWorkers: "block",
  });
  await context.addInitScript(() => {
    window.__justiceScaleLongTasks = [];
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__justiceScaleLongTasks.push(entry.duration);
      });
      observer.observe({ type: "longtask", buffered: true });
    } catch {
      // Long-task observation is not supported in every browser build.
    }
  });

  const page = await context.newPage();
  const collector = { current: null };
  attachPageObservers(page, collector);
  return { context, page, collector };
}

async function drainAndResetCollector(page, collector) {
  collector.current = null;
  await waitForApiQuiescence(collector);
  collector.pending.clear();
  collector.activeApiRequests.clear();
  collector.lastApiActivityAt = performance.now();
}

function failureDetails(error, stage) {
  return {
    stage,
    errorName: safeErrorName(error?.name),
    category: safeFailureCategory(error),
  };
}

function addFailedMeasurement(scenario, run, client, batch, mode, failure) {
  const failed = newMeasurement(scenario, run, client, batch, mode);
  failed.readiness = "failed";
  failed.failure = failure;
  measurements.push(failed);
}

async function runClientScenario(browser, storageState, scenario, run, client, barriers) {
  const batch = `${scenario.id}-c${CONCURRENCY}-b${String(run).padStart(2, "0")}`;
  let context = null;
  let page = null;
  let collector = null;
  let setupError = null;

  try {
    ({ context, page, collector } = await createProfiledPage(browser, storageState));
    await drainAndResetCollector(page, collector);
  } catch (error) {
    setupError = error;
  }

  try {
    const setupFailures = await barriers.setup(setupError ? failureDetails(setupError, "authentication-or-context-setup") : null);
    const firstFailure = setupFailures.find(Boolean);
    if (firstFailure) {
      addFailedMeasurement(scenario, run, client, batch, "cold", firstFailure);
      addFailedMeasurement(scenario, run, client, batch, "warm", firstFailure);
      return;
    }

    await barriers.cold();
    let coldArtifactFailure = null;
    try {
      await recordMeasurement(page, collector, scenario, run, client, batch, "cold", () => runScenarioMode(page, collector, scenario, "cold"));
    } catch (error) {
      if (error instanceof ArtifactWriteError) coldArtifactFailure = error;
      else addFailedMeasurement(scenario, run, client, batch, "cold", failureDetails(error, "cold-measurement"));
    }

    const batchArtifactFailures = await barriers.warm(coldArtifactFailure);
    const batchArtifactFailure = batchArtifactFailures.find(Boolean);
    if (batchArtifactFailure) throw batchArtifactFailure;

    try {
      await recordMeasurement(page, collector, scenario, run, client, batch, "warm", () => runScenarioMode(page, collector, scenario, "warm"));
    } catch (error) {
      if (error instanceof ArtifactWriteError) throw error;
      addFailedMeasurement(scenario, run, client, batch, "warm", failureDetails(error, "warm-measurement"));
    }
  } finally {
    if (context) await context.close();
  }
}

async function runScenarioMode(page, collector, scenario, mode) {
  if (scenario.mode === "navigation") {
    await navigateAndWait(page, scenario, collector);
    return {};
  }

  if (scenario.mode === "soldier-detail") {
    return mode === "cold"
      ? openSyntheticSoldier(page, scenario, collector)
      : reopenSyntheticSoldier(page, collector);
  }

  if (scenario.mode !== "calendar-team") {
    throw new Error(`Unsupported profiler workload: ${scenario.mode}`);
  }

  const calendarPageStartedAt = performance.now();
  await navigateAndWait(page, scenario, collector);
  const calendarPageReadyMs = roundMillis(performance.now() - calendarPageStartedAt);
  const teamScopeStartedAt = performance.now();
  await chooseSyntheticTeam(page, collector);
  return {
    calendarPageReadyMs,
    syntheticTeamScopeReadyMs: roundMillis(performance.now() - teamScopeStartedAt),
  };
}

async function main() {
  await prepareOutput();
  let browser = null;
  try {
    browser = await chromium.launch({ headless: true });
    browserVersion = browser.version();
    const storageState = await authenticateStorageState(browser);
    for (const scenario of selectedScenarios) {
      for (let run = 1; run <= RUNS; run += 1) {
        const barriers = {
          setup: createBarrier(CONCURRENCY),
          cold: createBarrier(CONCURRENCY),
          warm: createBarrier(CONCURRENCY),
        };
        const clients = Array.from({ length: CONCURRENCY }, (_, index) =>
          runClientScenario(browser, storageState, scenario, run, index + 1, barriers));
        const results = await Promise.allSettled(clients);
        const failures = results.filter((result) => result.status === "rejected");
        const artifactFailures = failures
          .map((result) => result.reason)
          .filter((error) => error instanceof ArtifactWriteError);
        if (artifactFailures.length) {
          throw new AggregateError(artifactFailures, "Benchmark artifact persistence failed.");
        }
        await persistOutput();
        if (failures.length) {
          throw new AggregateError(failures.map(({ reason }) => reason), "One or more scale-profile clients failed unexpectedly.");
        }
      }
    }
  } finally {
    if (browser) await browser.close();
    await persistOutput();
  }

  process.stdout.write(
    `Wrote ${measurements.length} sanitized measurements (concurrency=${CONCURRENCY}) to ${OUTPUT_PATH}\n`,
  );
}

await main();
