import PopoverDropdown from "./PopoverDropdown";

export interface CheckboxListItem {
  id: string;
  label: string;
}

interface Props {
  items: CheckboxListItem[];
  selected: string[];
  onChange: (ids: string[]) => void;
  triggerLabel: string;
  panelClassName?: string;
}

export default function CheckboxListDropdown({ items, selected, onChange, triggerLabel, panelClassName }: Props) {
  const allSelected = items.length > 0 && items.every((i) => selected.includes(i.id));

  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  }

  function toggleAll() {
    onChange(allSelected ? [] : items.map((i) => i.id));
  }

  return (
    <PopoverDropdown triggerLabel={triggerLabel} badgeCount={selected.length} panelClassName={panelClassName}>
      {() => (
        <>
          <label className="flex items-center gap-2 px-3 py-1.5 border-b dark:border-gray-600 cursor-pointer text-sm">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} />
            הכל
          </label>
          <div className="overflow-y-auto">
            {items.map((item) => (
              <label key={item.id} className="flex items-center gap-2 px-3 py-1 cursor-pointer text-sm hover:bg-gray-50 dark:hover:bg-gray-700">
                <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} />
                {item.label}
              </label>
            ))}
          </div>
        </>
      )}
    </PopoverDropdown>
  );
}
