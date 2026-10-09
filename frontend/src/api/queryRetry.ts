import { isAxiosError } from "axios";

export const MAX_QUERY_RETRIES = 2;

/** Retry only failures that can plausibly succeed on a second try. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  if (!isAxiosError(error)) return false;
  const status = error.response?.status;
  if (status === undefined) return true; // no response: network error
  return status === 502 || status === 504;
}
