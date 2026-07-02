import Fuse from "fuse.js";
import { useEffect, useMemo, useRef, useState } from "react";

interface Candidate {
  id: string;
  name: string;
}

interface Props {
  unresolvedName: string;
  candidates: Candidate[];
  onPick: (id: string) => void;
  disabled?: boolean;
}

export default function FuzzyPickerCombobox({
  unresolvedName,
  candidates,
  onPick,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(unresolvedName);
  const containerRef = useRef<HTMLDivElement>(null);

  const fuse = useMemo(
    () =>
      new Fuse(candidates, {
        keys: ["name"],
        threshold: 0.5,
        includeScore: true,
      }),
    [candidates],
  );

  const results = useMemo(() => {
    if (!query.trim()) return candidates.slice(0, 8);
    return fuse
      .search(query)
      .slice(0, 8)
      .map((r) => r.item);
  }, [fuse, query, candidates]);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    setQuery(unresolvedName);
  }, [unresolvedName]);

  return (
    <div ref={containerRef} className="relative inline-block">
      <input
        className="border rounded px-2 py-0.5 text-sm w-44 dark:bg-gray-700 dark:border-gray-600 text-red-600"
        value={query}
        disabled={disabled}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => setOpen(true)}
        placeholder={unresolvedName}
        dir="rtl"
      />
      {open && results.length > 0 && (
        <ul
          className="absolute z-50 bg-white dark:bg-gray-800 border dark:border-gray-600 rounded shadow-lg mt-1 w-56 max-h-48 overflow-y-auto text-sm"
          dir="rtl"
        >
          {results.map((c) => (
            <li
              key={c.id}
              className="px-3 py-1.5 hover:bg-indigo-50 dark:hover:bg-gray-700 cursor-pointer"
              onMouseDown={(e) => {
                e.preventDefault();
                setOpen(false);
                setQuery(c.name);
                onPick(c.id);
              }}
            >
              {c.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
