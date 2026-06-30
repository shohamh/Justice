import { Check, X } from "lucide-react";
import { useTranslation } from "react-i18next";

export function passwordValid(password: string): boolean {
  return password.length >= 10 && /[A-Za-z]/.test(password) && /[0-9]/.test(password);
}

interface Rule {
  key: "length" | "letter" | "digit";
  met: boolean;
  label: string;
}

export default function PasswordStrengthHint({ password }: { password: string }) {
  const { t } = useTranslation();

  if (password.length === 0) {
    return null;
  }

  const rules: Rule[] = [
    { key: "length", met: password.length >= 10, label: t("change_password.hint_length") },
    { key: "letter", met: /[A-Za-z]/.test(password), label: t("change_password.hint_letter") },
    { key: "digit", met: /[0-9]/.test(password), label: t("change_password.hint_digit") },
  ];

  return (
    <ul className="space-y-1 mt-1" data-testid="password-strength-hint">
      {rules.map((rule) => (
        <li
          key={rule.key}
          data-testid={`password-hint-${rule.key}`}
          data-met={rule.met}
          className={`flex items-center gap-1.5 text-xs ${rule.met ? "text-green-600 dark:text-green-400" : "text-gray-500 dark:text-gray-400"}`}
        >
          {rule.met ? <Check size={14} aria-hidden="true" /> : <X size={14} aria-hidden="true" />}
          <span>{rule.label}</span>
        </li>
      ))}
    </ul>
  );
}
