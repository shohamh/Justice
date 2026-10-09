import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { shouldRetryQuery } from "./queryRetry";

const httpError = (status: number) =>
  new AxiosError("fail", String(status), undefined, undefined, {
    status, statusText: "", headers: {}, config: { headers: new AxiosHeaders() }, data: {},
  });

describe("shouldRetryQuery", () => {
  it("never retries client or server errors that will not change", () => {
    for (const status of [400, 401, 403, 404, 422, 500, 503]) {
      expect(shouldRetryQuery(0, httpError(status))).toBe(false);
    }
  });
  it("does not retry a cancelled request", () => {
    expect(shouldRetryQuery(0, new AxiosError("canceled", "ERR_CANCELED"))).toBe(false);
  });
  it("retries network errors and gateway errors, at most twice", () => {
    expect(shouldRetryQuery(0, new AxiosError("Network Error"))).toBe(true);
    expect(shouldRetryQuery(1, httpError(502))).toBe(true);
    expect(shouldRetryQuery(0, httpError(504))).toBe(true);
    expect(shouldRetryQuery(2, new AxiosError("Network Error"))).toBe(false);
  });
});
