interface TabBarProps {
  tabs: string[];
  active: number;
  onChange: (i: number) => void;
  /** Optional per-tab count badges; a falsy entry renders no badge. */
  badges?: (number | null)[];
}

export default function TabBar({ tabs, active, onChange, badges }: TabBarProps) {
  return (
    <div className="flex border-b mb-6" dir="rtl">
      {tabs.map((label, i) => (
        <button
          key={i}
          onClick={() => onChange(i)}
          className={`px-2 py-2 text-xs font-medium border-b-2 -mb-px inline-flex items-center gap-1 ${
            active === i
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
          data-testid={`tab-${i}`}
        >
          {label}
          {badges?.[i] ? (
            <span
              className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 rounded-full bg-red-600 text-white text-[10px] font-semibold"
              data-testid={`tab-badge-${i}`}
            >
              {badges[i]}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

