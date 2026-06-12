interface TabBarProps {
  tabs: string[];
  active: number;
  onChange: (i: number) => void;
}

export default function TabBar({ tabs, active, onChange }: TabBarProps) {
  return (
    <div className="flex overflow-x-auto border-b mb-6" dir="rtl">
      {tabs.map((label, i) => (
        <button
          key={i}
          onClick={() => onChange(i)}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap shrink-0 ${
            active === i
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
          data-testid={`tab-${i}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
