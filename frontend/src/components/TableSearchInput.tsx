interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

export default function TableSearchInput({ value, onChange, placeholder, className }: Props) {
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder ?? "חיפוש..."}
      aria-label={placeholder ?? "חיפוש"}
      className={`w-full rounded border px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 ${className ?? ""}`}
    />
  );
}
