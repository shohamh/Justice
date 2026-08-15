import { render, screen } from "@testing-library/react";
import "../i18n";
import PasswordStrengthHint, { passwordValid } from "./PasswordStrengthHint";

describe("passwordValid", () => {
  test("rejects empty string", () => {
    expect(passwordValid("")).toBe(false);
  });

  test("rejects 9 characters", () => {
    expect(passwordValid("abcdefg1a".slice(0, 9))).toBe(false);
  });

  test("accepts exactly 8 characters with letter, digit, and symbol", () => {
    expect(passwordValid("abcde1!x")).toBe(true);
  });

  test("rejects letters only, 10+ chars", () => {
    expect(passwordValid("abcdefghij")).toBe(false);
  });

  test("rejects digits only, 10+ chars", () => {
    expect(passwordValid("1234567890")).toBe(false);
  });

  test("rejects passwords without a symbol", () => {
    expect(passwordValid("password123")).toBe(false);
  });

  test("rejects passwords without a letter", () => {
    expect(passwordValid("1234567!")).toBe(false);
  });

  test("rejects passwords without a digit", () => {
    expect(passwordValid("abcdefg!")).toBe(false);
  });
});

describe("PasswordStrengthHint", () => {
  test("renders nothing when password is empty", () => {
    const { container } = render(<PasswordStrengthHint password="" />);
    expect(container).toBeEmptyDOMElement();
  });

  test("shows all three rules when password is non-empty", () => {
    render(<PasswordStrengthHint password="abc" />);
    expect(screen.getByTestId("password-hint-length")).toBeInTheDocument();
    expect(screen.getByTestId("password-hint-letter")).toBeInTheDocument();
    expect(screen.getByTestId("password-hint-digit")).toBeInTheDocument();
  });

  test("marks length rule as met once 8+ chars are entered", () => {
    render(<PasswordStrengthHint password="abcdefgh" />);
    expect(screen.getByTestId("password-hint-length")).toHaveAttribute("data-met", "true");
  });

  test("marks length rule as unmet under 10 chars", () => {
    render(<PasswordStrengthHint password="abc" />);
    expect(screen.getByTestId("password-hint-length")).toHaveAttribute("data-met", "false");
  });

  test("marks digit rule as met when a digit is present", () => {
    render(<PasswordStrengthHint password="abc1" />);
    expect(screen.getByTestId("password-hint-digit")).toHaveAttribute("data-met", "true");
  });

  test("marks letter rule as unmet when password is digits only", () => {
    render(<PasswordStrengthHint password="123456" />);
    expect(screen.getByTestId("password-hint-letter")).toHaveAttribute("data-met", "false");
  });

  test("marks symbol rule as met when a symbol is present", () => {
    render(<PasswordStrengthHint password="abc!" />);
    expect(screen.getByTestId("password-hint-symbol")).toHaveAttribute("data-met", "true");
  });
});
