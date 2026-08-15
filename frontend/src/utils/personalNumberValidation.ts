export function personalNumberValid(personalNumber: string): boolean {
  return /^\d{7,8}$/.test(personalNumber);
}
