import { useState } from "react";
import { formatTimeInput, normalizeTime } from "../utils/timeMask";

interface Props {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  className?: string;
  "data-testid"?: string;
  required?: boolean;
}

export default function TimeInput({ value, onChange, id, className, required, ...rest }: Props) {
  const [invalid, setInvalid] = useState(false);

  return (
    <input
      id={id}
      data-testid={rest["data-testid"]}
      type="text"
      inputMode="numeric"
      placeholder="HH:MM"
      required={required}
      value={value}
      onChange={(e) => {
        const { display, valid } = formatTimeInput(e.target.value);
        setInvalid(!valid && display !== "");
        onChange(display);
      }}
      onBlur={() => {
        const { valid } = formatTimeInput(value);
        if (valid && value !== "") onChange(normalizeTime(value));
      }}
      className={`${className ?? ""} ${invalid ? "border-red-500 text-red-600 dark:border-red-500 dark:text-red-400" : ""}`.trim()}
    />
  );
}
