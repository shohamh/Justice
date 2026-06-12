interface TabBarProps {
  tabs: string[];
  active: number;
  onChange: (i: number) => void;
}

export default function TabBar({ tabs, active, onChange }: TabBarProps) {
  return (
    <div className="flex border-b mb-6" dir="rtl">
      {tabs.map((label, i) => (
        <button
          key={i}
          onClick={() => onChange(i)}
          className={`px-2 py-2 text-xs font-medium border-b-2 -mb-px ${
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
