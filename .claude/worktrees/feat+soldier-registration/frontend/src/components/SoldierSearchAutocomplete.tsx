import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { listSoldiers, SoldierDTO } from "../api/soldiers";

interface Props {
  onSelect: (soldier: SoldierDTO | null) => void;
  onCreateNew: (personalNumber: string, fullName: string) => void;
}

export default function SoldierSearchAutocomplete({ onSelect, onCreateNew }: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [results, setResults] = useState<SoldierDTO[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [selected, setSelected] = useState<SoldierDTO | null>(null);
  const [newPn, setNewPn] = useState("");
  const [newName, setNewName] = useState("");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      const all = await listSoldiers();
      setSoldiers(all);
    })();
  }, []);

  useEffect(() => {
    if (!query.trim() || selected) {
      setResults([]);
      return;
    }
    const q = query.toLowerCase();
    const filtered = soldiers.filter(
      (s) => s.full_name.toLowerCase().includes(q) || s.personal_number.includes(q)
    );
    setResults(filtered.slice(0, 10));
  }, [query, soldiers, selected]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function handleSelect(s: SoldierDTO) {
    setSelected(s);
    setQuery(`${s.full_name} (${s.personal_number})`);
    setShowDropdown(false);
    onSelect(s);
  }

  function handleClear() {
    setSelected(null);
    setQuery("");
    onSelect(null);
  }

  function handleCreateNew() {
    setShowCreateForm(true);
    setShowDropdown(false);
  }

  function handleSubmitNew() {
    onCreateNew(newPn || query, newName || query);
    setShowCreateForm(false);
    setNewPn("");
    setNewName("");
  }

  return (
    <div ref={ref} className="relative">
      {!showCreateForm ? (
        <>
          <input
            className="border rounded p-1 w-full"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setShowDropdown(true);
            }}
            onFocus={() => setShowDropdown(true)}
            placeholder={t("team.search_soldier_placeholder")}
            data-testid="soldier-search-input"
          />
          {showDropdown && results.length > 0 && (
            <ul className="absolute z-10 bg-white border rounded w-full mt-1 shadow-lg max-h-48 overflow-y-auto" data-testid="soldier-search-dropdown">
              {results.map((s) => (
                <li
                  key={s.id}
                  className="px-2 py-1 hover:bg-indigo-50 cursor-pointer text-sm"
                  onClick={() => handleSelect(s)}
                  data-testid={`soldier-search-result-${s.personal_number}`}
                >
                  {s.full_name} ({s.personal_number})
                </li>
              ))}
              <li
                className="px-2 py-1 hover:bg-gray-50 cursor-pointer text-sm text-indigo-600 border-t"
                onClick={handleCreateNew}
                data-testid="soldier-search-create-new"
              >
                {t("team.create_new_soldier")}
              </li>
            </ul>
          )}
          {selected && (
            <button className="text-xs text-red-500 mt-1" onClick={handleClear} data-testid="soldier-search-clear">
              {t("team.cancel")}
            </button>
          )}
        </>
      ) : (
        <div className="space-y-2 border rounded p-2 mt-1" data-testid="soldier-create-form">
          <input
            className="border rounded p-1 w-full"
            value={newPn}
            onChange={(e) => setNewPn(e.target.value)}
            placeholder={t("team.personal_number")}
            data-testid="soldier-create-pn"
          />
          <input
            className="border rounded p-1 w-full"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("team.full_name")}
            data-testid="soldier-create-name"
          />
          <button className="bg-indigo-600 text-white px-3 py-1 rounded text-sm" onClick={handleSubmitNew} data-testid="soldier-create-submit">
            {t("team.add_soldier")}
          </button>
        </div>
      )}
    </div>
  );
}
