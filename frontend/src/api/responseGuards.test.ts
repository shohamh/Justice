import { describe, expect, it } from "vitest";
import {
  optionalArrayResponse,
  requiredArrayResponse,
  requiredNumberField,
  requiredObjectResponse,
  requiredStringArrayField,
} from "./responseGuards";

describe("responseGuards", () => {
  it("returns an empty list for malformed optional array payloads", () => {
    expect(optionalArrayResponse({ detail: "unexpected response" })).toEqual([]);
    expect(optionalArrayResponse(null)).toEqual([]);
  });

  it("preserves valid optional array payloads", () => {
    expect(optionalArrayResponse(["a", "b"])).toEqual(["a", "b"]);
  });

  it("throws for malformed required array payloads", () => {
    expect(() => requiredArrayResponse({ detail: "unexpected response" }, "bad array")).toThrow(
      "bad array",
    );
  });

  it("throws for malformed required object payloads", () => {
    expect(() => requiredObjectResponse(null, "bad object")).toThrow("bad object");
    expect(() => requiredObjectResponse([], "bad object")).toThrow("bad object");
  });

  it("throws for malformed required numeric fields", () => {
    expect(() => requiredNumberField("3", "bad number")).toThrow("bad number");
  });

  it("throws for malformed required string-array fields", () => {
    expect(() => requiredStringArrayField(["valid", 7], "bad strings")).toThrow("bad strings");
    expect(() => requiredStringArrayField({ detail: "unexpected response" }, "bad strings")).toThrow(
      "bad strings",
    );
  });
});
