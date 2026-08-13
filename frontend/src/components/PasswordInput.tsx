import { InputHTMLAttributes, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  "data-testid"?: string;
};

export default function PasswordInput({ className, ...props }: PasswordInputProps) {
  const [visible, setVisible] = useState(false);
  const testId = props["data-testid"];

  return (
    <div className="relative">
      <input
        {...props}
        type={visible ? "text" : "password"}
        className={`${className ?? ""} pl-9`.trim()}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        aria-label={visible ? "הסתר סיסמה" : "הצג סיסמה"}
        className="absolute inset-y-0 left-0 flex items-center px-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        {visible ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}
