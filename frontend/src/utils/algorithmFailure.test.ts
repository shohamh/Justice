import { parseInterrupted } from "./algorithmFailure";

describe("parseInterrupted", () => {
  test("returns null for null error_message", () => {
    expect(parseInterrupted(null)).toBeNull();
  });

  test("parses the structured INTERRUPTED shape", () => {
    expect(parseInterrupted(JSON.stringify({ status: "INTERRUPTED", reason: "server_restarted" })))
      .toEqual({ reason: "server_restarted" });
    expect(parseInterrupted(JSON.stringify({ status: "INTERRUPTED", reason: "timed_out" })))
      .toEqual({ reason: "timed_out" });
  });

  test("falls back to legacy bare-string error messages", () => {
    expect(parseInterrupted("orphaned_on_restart")).toEqual({ reason: "server_restarted" });
    expect(parseInterrupted("timed_out")).toEqual({ reason: "timed_out" });
  });

  test("returns null for an unrelated bare string", () => {
    expect(parseInterrupted("cancelled_by_user")).toBeNull();
  });

  test("returns null for a different structured failure shape (e.g. INFEASIBLE)", () => {
    expect(parseInterrupted(JSON.stringify({ status: "INFEASIBLE", relaxed: [], reasons: [] })))
      .toBeNull();
  });

  test("returns null for a PARTIAL result that merely happened to time out", () => {
    // Salvaged partial runs use status "done", not "failed" — but even if this
    // shape reached the parser, it must not be mistaken for INTERRUPTED.
    expect(parseInterrupted(JSON.stringify({ status: "PARTIAL", timed_out: true })))
      .toBeNull();
  });
});
