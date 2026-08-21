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

function isoToDigits(iso: string | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  return m ? `${m[3]}${m[2]}${m[1]}` : "";
}

function expandTwoDigitYear(yearDigits: string): string {
  const year = Number(yearDigits) < 50 ? 2000 + Number(yearDigits) : 1900 + Number(yearDigits);
  return String(year);
}

function displayToIso(display: string): string | null {
  const m = /^(\d{2})\/(\d{2})\/(\d{2}|\d{4})$/.exec(display);
  if (!m) return null;
  const [, dd, mm, yearDigits] = m;
  const year = yearDigits.length === 2
    ? Number(expandTwoDigitYear(yearDigits))
    : Number(yearDigits);
  const yyyy = String(year).padStart(4, "0");
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

function formatDateDigits(digits: string, expandShortYear = true): string {
  if (digits.length === 6 && expandShortYear) {
    return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${expandTwoDigitYear(digits.slice(4))}`;
  }
  return formatAsTyped(digits);
}

export default function DateInput({
  value, defaultValue, onChange, onBlur, className, disabled, required, autoFocus, min, max, id, ...rest
}: DateInputProps) {
  const isControlled = value !== undefined;
  const [text, setText] = useState(() => isoToDisplay(value ?? defaultValue));
  const rawDigitsRef = useRef(isoToDigits(value ?? defaultValue));
  const isTypingRef = useRef(false);
  const nativeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isControlled && !isTypingRef.current) {
      setText(isoToDisplay(value));
      rawDigitsRef.current = isoToDigits(value);
    }
  }, [isControlled, value]);

  function commit(iso: string) {
    if (onChange) onChange(iso);
    else onBlur?.(iso);
  }

  function handleTextChange(raw: string, deleting = false) {
    // Programmatic value assignment (e.g. autofill or a test driving the
    // field via a raw change event) may hand us an already-ISO value
    // directly, rather than the dd/mm/yyyy digits a human would type.
    // Detect that shape up front so it commits as-is instead of being
    // misread as freeform digit entry — but still route it through the
    // same calendar-validity roundtrip every other commit path uses, so
    // a bogus value like "2026-13-40" is rejected rather than silently
    // accepted.
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
      const validatedIso = displayToIso(isoToDisplay(raw));
      if (!validatedIso) return;
      setText(isoToDisplay(validatedIso));
      rawDigitsRef.current = isoToDigits(validatedIso);
      isTypingRef.current = false;
      commit(validatedIso);
      return;
    }
    const typedDigits = raw.replace(/\D/g, "");
    const previousDigits = rawDigitsRef.current;
    // A six-digit date is displayed with an implied four-digit year (e.g.
    // 010320 -> 01/03/2020). If the user types another digit, the browser
    // reports the already-expanded display plus that new digit. Recover the
    // user's raw buffer so the implied zero does not consume their keystroke.
    const impliedDisplayDigits = previousDigits.length === 6
      ? `${previousDigits.slice(0, 4)}${expandTwoDigitYear(previousDigits.slice(4))}`
      : "";
    const digits = impliedDisplayDigits && typedDigits.startsWith(impliedDisplayDigits)
      ? `${previousDigits}${typedDigits.slice(impliedDisplayDigits.length)}`.slice(0, 8)
      : typedDigits.slice(0, 8);
    const formatted = formatDateDigits(digits, !deleting);
    rawDigitsRef.current = digits;
    isTypingRef.current = true;
    setText(formatted);
    if (formatted === "") {
      commit("");
      return;
    }
    if (digits.length === 6 || digits.length === 8) {
      const iso = displayToIso(formatted);
      if (iso) commit(iso);
    }
  }

  function handleTextBlur() {
    const iso = displayToIso(text);
    isTypingRef.current = false;
    onBlur?.(iso ?? "");
  }

  function handleNativePick(raw: string) {
    setText(isoToDisplay(raw));
    rawDigitsRef.current = isoToDigits(raw);
    isTypingRef.current = false;
    commit(raw);
  }

  function handleClear() {
    setText("");
    rawDigitsRef.current = "";
    isTypingRef.current = false;
    commit("");
  }

  // Callers style the text field directly (e.g. `w-full` or `flex-1`)
  // expecting it to fill its parent, same as the native input it replaces —
  // the wrapper needs the same sizing class or the flex row won't stretch.
  // `flex-1` matters when a caller nests DateInput in its own flex row
  // (e.g. next to a "clear" button): that class lands on the inner
  // <input> (below), but the WRAPPER is the actual flex item of the
  // caller's row, so without flex-grow on the wrapper too, it sits at its
  // own content width — width:auto default — leaving a gap before the
  // input even though the caller's `w-full` div around it stretches fine.
  //
  // Block (not inline-flex): when a caller places this directly after a
  // label's <span> with no wrapping container (the common
  // `<label className="block"><span>...</span><DateInput .../></label>`
  // pattern), an inline-level wrapper only stacks onto its own line via the
  // "inline element sized to 100% width can't fit next to preceding inline
  // content, so it wraps" trick. That's fragile once the wrapper contains
  // several inline children (text input, calendar button, hidden native
  // input) inside an RTL bidi context — Chromium/WebKit can render the
  // fields overlapping instead of stacking (seen on mobile). A genuinely
  // block-level wrapper stacks unconditionally, and is blockified back to a
  // normal flex item on the rare caller that nests this inside its own flex
  // row (e.g. next to a "clear" button), so this is safe either way.
  const wrapperClassName = `flex items-center gap-1${className?.includes("w-full") ? " w-full" : ""}${className?.includes("flex-1") ? " flex-1 min-w-0" : ""}`;

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
        onChange={e => handleTextChange(e.target.value, (e.nativeEvent as InputEvent).inputType?.startsWith("delete"))}
        onBlur={handleTextBlur}
        // flex-1 min-w-0 always applied (not left to each caller's className):
        // the button next to it is shrink-0, so without these the text
        // input's flex-basis defaults to its own width (100% when the
        // caller passes w-full), forcing the flex-shrink algorithm to
        // squeeze it down to share the row with its siblings instead of
        // actually filling the row — seen as the date text clipped to 1-2
        // characters. min-w-0 overrides the default min-width:auto that
        // would otherwise still block shrinking below content size.
        className={`flex-1 min-w-0 ${className ?? ""}`}
      />
      {!disabled && text !== "" && (
        <button
          type="button"
          tabIndex={-1}
          aria-label="נקה"
          onClick={handleClear}
          className="shrink-0 w-4 h-4 flex items-center justify-center rounded-full bg-gray-300 dark:bg-gray-600 text-white text-[10px] leading-none hover:bg-gray-400 dark:hover:bg-gray-500"
        >
          ×
        </button>
      )}
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
