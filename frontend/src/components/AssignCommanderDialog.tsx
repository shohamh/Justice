import { FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, updateNode } from "../api/hierarchy";
import { listSoldierRosterPage, SoldierRosterItemDTO } from "../api/soldiers";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  node: NodeDTO;
  onClose: () => void;
  onAssigned: () => void;
}

export default function AssignCommanderDialog({ node, onClose, onAssigned }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierRosterItemDTO[]>([]);
  const [selectedId, setSelectedId] = useState(node.commander_id ?? "");
  const [inputText, setInputText] = useState(node.commander_name ?? "");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSoldiers([]);
    const timeout = window.setTimeout(() => {
      setLoading(true);
      void listSoldierRosterPage({
        search: inputText.trim(),
        page_size: 20,
        sort: "full_name",
        descending: false,
        signal: controller.signal,
      })
        .then((page) => setSoldiers(page.items))
        .catch(() => {
          if (!controller.signal.aborted) setSoldiers([]);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 200);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [inputText, open]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const filtered = soldiers.slice(0, 20);

  function selectSoldier(s: SoldierRosterItemDTO) {
    setSelectedId(s.id);
    setInputText(`${s.full_name} (${s.personal_number})`);
    setOpen(false);
  }

  function clearSelection() {
    setSelectedId("");
    setInputText("");
    setOpen(false);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await updateNode(node.id, { commander_id: selectedId || null });
    onAssigned();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96"
        onClick={(e) => e.stopPropagation()}
        data-testid="assign-commander-dialog"
      >
        <h3 className="font-semibold mb-4 dark:text-gray-100">
          {t("team.assign_commander")}: {node.name}
        </h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <div ref={containerRef} className="relative">
            <div className="flex gap-1">
              <input
                className="border rounded p-1 flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={inputText}
                onChange={(e) => {
                  setInputText(e.target.value);
                  setSelectedId("");
                  setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                placeholder={t("team.search_soldier_placeholder")}
                data-testid="commander-search"
                autoComplete="off"
              />
              {(selectedId || inputText) && (
                <button
                  type="button"
                  className="text-gray-400 hover:text-gray-600 px-1"
                  onClick={clearSelection}
                  aria-label="נקה"
                >
                  ✕
                </button>
              )}
            </div>
            {open && loading && <p role="status" className="px-3 py-2 text-xs text-gray-500">{t("team.roster_loading")}</p>}
            {open && !loading && filtered.length > 0 && (
              <ul className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto">
                {filtered.map((s) => (
                  <li
                    key={s.id}
                    className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      selectSoldier(s);
                    }}
                    data-testid={`commander-option-${s.id}`}
                  >
                    {s.full_name}{" "}
                    <span className="text-gray-400 text-xs">
                      ({s.personal_number}) [{s.role}]
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:text-gray-100 dark:border-gray-600" onClick={onClose}>
              {t("team.cancel")}
            </button>
            <button
              type="submit"
              className="bg-indigo-600 text-white px-3 py-1 rounded"
              data-testid="commander-submit"
            >
              {t("approvals.approve")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
