import Fuse from "fuse.js";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface ComboboxItem {
  id: string;
  name: string;
  /** Tree-indentation depth (0 = top level). Renders a leading "└" marker for depth > 0. */
  depth?: number;
  /** Group header text. A header row is rendered before the first item of each new group. */
  group?: string;
  disabled?: boolean;
}

interface ComboboxProps {
  label?: string;
  items: ComboboxItem[];
  value: string;
  onChange: (id: string) => void;
  /** When set, renders a selectable first row with this text that calls onChange(""). */
  placeholder?: string;
  testId?: string;
  /** When true, the whole combobox is read-only: the input is disabled and the dropdown never opens. */
  disabled?: boolean;
}

// Combobox with Fuse.js fuzzy search — dropdown rendered via portal so it
// escapes overflow-y-auto containers (modals, panels).
export default function Combobox({ label, items, value, onChange, placeholder, testId, disabled }: ComboboxProps) {
  const allItems: ComboboxItem[] = useMemo(
    () => (placeholder !== undefined ? [{ id: "", name: placeholder }, ...items] : items),
    [items, placeholder]
  );

  // Looks up in `items`, not `allItems`: the placeholder's own synthetic row
  // (id "") would otherwise match an unselected value and seed the input with
  // literal placeholder text — indistinguishable from real content, so typing
  // over it (e.g. "רסן") concatenated onto it instead of replacing it. The
  // native `placeholder` attribute below shows the hint text instead.
  const [query, setQuery] = useState(() => items.find(i => i.id === value)?.name ?? "");
  // Separate from `query` (the input's displayed text) so that opening the list while a value
  // is already selected shows the full list, rather than fuzzy-filtering by the selected name.
  const [filterQuery, setFilterQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const listboxId = useId();

  const fuse = useMemo(() => new Fuse(allItems, { keys: ["name"], threshold: 0.4 }), [allItems]);
  const results = filterQuery.trim() === "" ? allItems : fuse.search(filterQuery).map(r => r.item);

  useLayoutEffect(() => {
    if (open && inputRef.current) setRect(inputRef.current.getBoundingClientRect());
  }, [open]);

  // Sync displayed text when external value changes (e.g. after a quick-add selects a new item)
  useEffect(() => {
    const match = items.find(i => i.id === value);
    setQuery(match ? match.name : "");
  }, [value, items]);

  // Reset the highlight whenever the result list changes or the dropdown opens/closes,
  // so a stale index from a previous filter pass never lingers.
  useEffect(() => {
    setHighlightedIndex(-1);
  }, [open, results.length, filterQuery]);

  const selectItem = (item: ComboboxItem) => {
    if (item.disabled) return;
    onChange(item.id);
    // The synthetic placeholder row (id "") clears the selection — show that
    // as empty (native placeholder), not its literal label, for the same
    // reason the initial/synced query never uses it (see `query` above).
    setQuery(item.id === "" ? "" : item.name);
    setOpen(false);
  };

  const selectExactMatch = () => {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return false;
    const match = allItems.find(item => item.name === normalizedQuery && !item.disabled);
    if (!match) return false;
    selectItem(match);
    return true;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightedIndex(prev => {
        for (let i = prev + 1; i < results.length; i++) {
          if (!results[i].disabled) return i;
        }
        return prev;
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightedIndex(prev => {
        for (let i = prev - 1; i >= 0; i--) {
          if (!results[i].disabled) return i;
        }
        return prev;
      });
    } else if (e.key === "Enter") {
      if (highlightedIndex >= 0 && highlightedIndex < results.length) {
        const item = results[highlightedIndex];
        if (!item.disabled) {
          e.preventDefault();
          selectItem(item);
        }
      } else if (selectExactMatch()) {
        e.preventDefault();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div>
      {label && <span className="text-xs text-gray-500 dark:text-gray-400 block mb-0.5">{label}</span>}
      <input
        ref={inputRef}
        type="text"
        value={query}
        placeholder={placeholder}
        autoComplete="off"
        data-testid={testId}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        disabled={disabled}
        onChange={e => { setQuery(e.target.value); setFilterQuery(e.target.value); setOpen(true); }}
        onFocus={() => { setOpen(true); setFilterQuery(""); if (inputRef.current) setRect(inputRef.current.getBoundingClientRect()); }}
        onBlur={() => setTimeout(() => {
          if (!selectExactMatch()) setOpen(false);
        }, 150)}
        onKeyDown={handleKeyDown}
        className="block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 disabled:opacity-60 disabled:cursor-not-allowed"
      />
      {!disabled && open && results.length > 0 && rect && createPortal(
        <ul
          id={listboxId}
          role="listbox"
          style={{
            position: "fixed",
            top: rect.bottom + 2,
            width: Math.max(rect.width, 240),
            left: Math.min(rect.left, window.innerWidth - Math.max(rect.width, 240) - 4),
            zIndex: 9999,
          }}
          className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto"
        >
          {results.map((item, idx) => {
            const showGroup = item.group !== undefined && (idx === 0 || results[idx - 1].group !== item.group);
            const depth = item.depth ?? 0;
            const highlighted = idx === highlightedIndex;
            return (
              <li
                key={item.id}
                role="option"
                aria-selected={value === item.id}
                aria-disabled={item.disabled || undefined}
              >
                {showGroup && (
                  <div className="px-3 pt-2 pb-0.5 text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase">
                    {item.group}
                  </div>
                )}
                <button
                  type="button"
                  disabled={item.disabled}
                  onPointerDown={e => {
                    if (item.disabled) return;
                    e.preventDefault(); // keep input focused so blur doesn't fire before onChange
                  }}
                  onPointerUp={e => {
                    if (item.disabled) return;
                    // Select on pointer-up (a completed tap), not pointer-down: pointerdown fires the
                    // instant a finger touches the screen, before a scroll gesture can be distinguished
                    // from a tap. A touch that turns into a scroll fires pointercancel instead of
                    // pointerup, so this naturally lets touch-scrolling the dropdown work.
                    e.preventDefault();
                    selectItem(item);
                  }}
                  style={depth > 0 ? { paddingRight: `${0.75 + depth * 1.25}rem` } : undefined}
                  className={`w-full flex items-center gap-1 text-right px-3 py-2 text-sm ${
                    item.disabled
                      ? "text-gray-400 dark:text-gray-600 cursor-not-allowed"
                      : `hover:bg-gray-50 dark:hover:bg-gray-700 ${highlighted ? "bg-gray-100 dark:bg-gray-700" : ""} ${
                          value === item.id ? "font-semibold text-indigo-600 dark:text-indigo-300" : "text-gray-700 dark:text-gray-200"
                        }`
                  }`}
                >
                  {depth > 0 && <span className="text-gray-300 dark:text-gray-600 text-xs select-none">└</span>}
                  {item.name}
                </button>
              </li>
            );
          })}
        </ul>,
        document.body
      )}
    </div>
  );
}
