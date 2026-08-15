export function personalConstraintComplete(startDate: string, endDate: string, reason: string): boolean {
  return Boolean(startDate && endDate && reason.trim());
}
