import { useEffect, useRef, useState } from "react";

/**
 * Chromium ignores the `lang` attribute on <input type="date"> and always
 * formats the text field using the browser/OS locale, so a Hebrew page still
 * shows mm/dd/yyyy on an en-US machine. This wraps a real dd/mm/yyyy text
 * field (always correct, in our control) with a hidden native date input
 * that only supplies the calendar-picker popup, triggered via the button.
 */
interface DateInputProps {
  value?: string;
  defaultValue?: string;
  onChange?: (isoValue: string) => void;
  onBlur?: (isoValue: string) => void;
  className?: string;
  disabled?: boolean;
  required?: boolean;
  autoFocus?: boolean;
  min?: string;
  max?: string;
  id?: string;
  "data-testid"?: string;
}

function isoToDisplay(iso: string | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!m) return "";
  return `${m[3]}/${m[2]}/${m[1]}`;
}

function displayToIso(display: string): string | null {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(display);
  if (!m) return null;
  const [, dd, mm, yyyy] = m;
  const d = Number(dd), mo = Number(mm), y = Number(yyyy);
  const dt = new Date(y, mo - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
  return `${yyyy}-${mm}-${dd}`;
}

function formatAsTyped(digits: string): string {
  if (digits.length > 4) return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
  if (digits.length > 2) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return digits;
}

export default function DateInput({
  value, defaultValue, onChange, onBlur, className, disabled, required, autoFocus, min, max, id, ...rest
}: DateInputProps) {
  const isControlled = value !== undefined;
  const [text, setText] = useState(() => isoToDisplay(value ?? defaultValue));
  const nativeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isControlled) setText(isoToDisplay(value));
  }, [isControlled, value]);

  function commit(iso: string) {
    if (onChange) onChange(iso);
    else onBlur?.(iso);
  }

  function handleTextChange(raw: string) {
    const digits = raw.replace(/\D/g, "").slice(0, 8);
    const formatted = formatAsTyped(digits);
    setText(formatted);
    if (formatted === "") {
      commit("");
      return;
    }
    if (formatted.length === 10) {
      const iso = displayToIso(formatted);
      if (iso) commit(iso);
    }
  }

  function handleTextBlur() {
    const iso = displayToIso(text);
    onBlur?.(iso ?? "");
  }

  function handleNativePick(raw: string) {
    setText(isoToDisplay(raw));
    commit(raw);
  }

  // Callers style the text field directly (e.g. `w-full`) expecting it to
  // fill its parent, same as the native input it replaces — the wrapper
  // needs the same sizing class or the flex row won't stretch.
  const wrapperClassName = `inline-flex items-center gap-1${className?.includes("w-full") ? " w-full" : ""}`;

  return (
    <span className={wrapperClassName}>
      <input
        type="text"
        inputMode="numeric"
        dir="ltr"
        placeholder="dd/mm/yyyy"
        value={text}
        disabled={disabled}
        required={required}
        autoFocus={autoFocus}
        id={id}
        data-testid={rest["data-testid"]}
        onChange={e => handleTextChange(e.target.value)}
        onBlur={handleTextBlur}
        className={className}
      />
      <button
        type="button"
        tabIndex={-1}
        disabled={disabled}
        aria-label="פתח לוח שנה"
        onClick={() => {
          const el = nativeRef.current;
          if (!el) return;
          if (typeof el.showPicker === "function") el.showPicker();
          else el.focus();
        }}
        className="shrink-0 text-gray-400 hover:text-gray-600 disabled:opacity-40 text-xs leading-none"
      >
        📅
      </button>
      <input
        ref={nativeRef}
        type="date"
        tabIndex={-1}
        min={min}
        max={max}
        value={displayToIso(text) ?? ""}
        onChange={e => handleNativePick(e.target.value)}
        className="sr-only"
      />
    </span>
  );
}
