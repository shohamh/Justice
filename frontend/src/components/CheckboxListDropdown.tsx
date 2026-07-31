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
  /** Overrides the badge count shown on the trigger; defaults to `selected.length`. */
  badgeCount?: number;
  /** Optional tooltip shown on the trigger button. */
  title?: string;
  /** Overrides the trigger button's default className entirely, when set. */
  triggerClassName?: string;
  /** Optional `dir` attribute applied to the panel (e.g. "rtl" for right-edge-anchored panels). */
  panelDir?: "rtl" | "ltr";
}

export default function CheckboxListDropdown({
  items,
  selected,
  onChange,
  triggerLabel,
  panelClassName,
  badgeCount,
  title,
  triggerClassName,
  panelDir,
}: Props) {
  const allSelected = items.length > 0 && items.every((i) => selected.includes(i.id));

  function toggle(id: string) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  }

  function toggleAll() {
    onChange(allSelected ? [] : items.map((i) => i.id));
  }

  return (
    <PopoverDropdown
      triggerLabel={triggerLabel}
      badgeCount={badgeCount ?? selected.length}
      panelClassName={panelClassName}
      title={title}
      triggerClassName={triggerClassName}
      panelDir={panelDir}
    >
      {() => (
        <>
          <label className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer border-b border-gray-100 dark:border-gray-700 text-xs font-medium text-gray-700 dark:text-gray-200">
            <input type="checkbox" checked={allSelected} onChange={toggleAll} className="accent-indigo-600" />
            הכל
          </label>
          <div className="overflow-y-auto">
            {items.map((item) => (
              <label key={item.id} className="flex items-center gap-2 px-3 py-1 cursor-pointer text-xs hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300">
                <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} className="accent-indigo-600" />
                {item.label}
              </label>
            ))}
          </div>
        </>
      )}
    </PopoverDropdown>
  );
}
