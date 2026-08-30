type UnknownRecord = Record<string, unknown>;

export function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function optionalArrayResponse<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function requiredArrayResponse<T>(value: unknown, errorMessage: string): T[] {
  if (!Array.isArray(value)) {
    throw new Error(errorMessage);
  }
  return value as T[];
}

export function requiredObjectResponse(value: unknown, errorMessage: string): UnknownRecord {
  if (!isRecord(value)) {
    throw new Error(errorMessage);
  }
  return value;
}

export function requiredNumberField(value: unknown, errorMessage: string): number {
  if (typeof value !== "number") {
    throw new Error(errorMessage);
  }
  return value;
}

export function requiredStringArrayField(value: unknown, errorMessage: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(errorMessage);
  }
  return value as string[];
}
