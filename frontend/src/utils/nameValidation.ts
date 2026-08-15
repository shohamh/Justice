export function fullNameValid(fullName: string): boolean {
  return fullName.length <= 100 && fullName.trim().split(/\s+/).filter(Boolean).length >= 2;
}
