#!/usr/bin/env node
import { readFileSync } from "node:fs";

const [, , afterPath, beforePath] = process.argv;
if (!afterPath) {
  console.error("Usage: summarize-scale-pages.mjs <artifact.json> [<baseline.json>]");
  process.exit(2);
}

const median = (values) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};
const round = (value) => (value === null ? "-" : Math.round(value));

function load(path) {
  const artifact = JSON.parse(readFileSync(path, "utf8"));
  const rows = new Map();
  for (const m of artifact.measurements) {
    if (m.readiness !== "ready") continue;
    const key = `${m.scenario} ${m.mode}`;
    const row = rows.get(key) ?? { ready: [], fcp: [], requests: [], endpoints: new Map() };
    row.ready.push(m.pageReadyMs);
    if (m.firstContentfulPaintMs != null) row.fcp.push(m.firstContentfulPaintMs);
    row.requests.push(m.apiRequestCount ?? m.apiResponses.length);
    const perRun = new Map();
    for (const a of m.apiResponses) {
      const e = perRun.get(a.endpoint) ?? { n: 0, ms: 0 };
      e.n += 1;
      e.ms += a.durationMs;
      perRun.set(a.endpoint, e);
    }
    for (const [endpoint, e] of perRun) {
      const agg = row.endpoints.get(endpoint) ?? { n: [], ms: [] };
      agg.n.push(e.n);
      agg.ms.push(e.ms);
      row.endpoints.set(endpoint, agg);
    }
    rows.set(key, row);
  }
  return { artifact, rows };
}

const after = load(afterPath);
const before = beforePath ? load(beforePath) : null;
console.log(`# ${afterPath} (concurrency ${after.artifact.concurrency})`);
for (const [key, row] of [...after.rows].sort()) {
  const p = (values, q) => {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(q * sorted.length) - 1)] : null;
  };
  const base = before?.rows.get(key);
  const delta = base ? ` (baseline ready p50 ${round(median(base.ready))}, FCP p50 ${round(median(base.fcp))}, req ${round(median(base.requests))})` : "";
  console.log(
    `${key.padEnd(46)} ready p50/p95 ${round(median(row.ready))}/${round(p(row.ready, 0.95))}  FCP p50/p95 ${round(median(row.fcp))}/${round(p(row.fcp, 0.95))}  req ${round(median(row.requests))}${delta}`,
  );
  const top = [...row.endpoints]
    .map(([endpoint, agg]) => ({ endpoint, ms: median(agg.ms), n: median(agg.n) }))
    .sort((a, b) => b.ms - a.ms)
    .slice(0, 5);
  for (const t of top) console.log(`    ${String(round(t.ms)).padStart(7)} ms  x${t.n}  ${t.endpoint}`);
}
