import Fuse from "fuse.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { assignDmScope, removeDmScope } from "../api/dmScope";
import { SoldierDTO, listSoldiers } from "../api/soldiers";
import { useModalBackClose } from "../hooks/useModalBackClose";
import MessageDialog from "./MessageDialog";

interface Props {
  node: NodeDTO;
  onClose: () => void;
  onChanged: () => void;
}

export default function AssignDutyManagersDialog({ node, onClose, onChanged }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [inputText, setInputText] = useState("");
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void listSoldiers().then(setSoldiers);
  }, []);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const fuse = useMemo(
    () => new Fuse(soldiers, { keys: ["full_name", "personal_number"], threshold: 0.4 }),
    [soldiers]
  );

  const assignedIds = new Set(node.duty_managers.map((dm) => dm.soldier_id));
  const candidateSoldiers = soldiers.filter((s) => !assignedIds.has(s.id));
  const filtered = inputText
    ? fuse.search(inputText).map((r) => r.item).filter((s) => !assignedIds.has(s.id)).slice(0, 20)
    : candidateSoldiers.slice(0, 20);

  async function handleAdd(s: SoldierDTO) {
    setInputText("");
    setOpen(false);
    try {
      await assignDmScope(s.id, node.id);
      onChanged();
    } catch {
      setMessage(t("errors.generic", "שגיאה"));
    }
  }

  async function handleRemove(scopeId: string) {
    try {
      await removeDmScope(scopeId);
      onChanged();
    } catch {
      setMessage(t("errors.generic", "שגיאה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96"
        onClick={(e) => e.stopPropagation()}
        data-testid="assign-duty-managers-dialog"
      >
        <h3 className="font-semibold mb-4 dark:text-gray-100">
          {t("team.assign_duty_managers")}: {node.name}
        </h3>

        {node.duty_managers.length === 0 ? (
          <p className="text-sm text-gray-500 mb-3">{t("team.no_duty_managers")}</p>
        ) : (
          <ul className="space-y-1 mb-3" data-testid="duty-managers-list">
            {node.duty_managers.map((dm) => (
              <li
                key={dm.scope_id}
                className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1"
              >
                <span>{dm.name}</span>
                <button
                  type="button"
                  className="text-red-500 hover:text-red-700 text-xs"
                  onClick={() => void handleRemove(dm.scope_id)}
                  data-testid={`remove-dm-${dm.scope_id}`}
                >
                  {t("notifications.remove")}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div ref={containerRef} className="relative">
          <input
            className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={inputText}
            onChange={(e) => { setInputText(e.target.value); setOpen(true); }}
            onFocus={() => setOpen(true)}
            placeholder={t("team.search_soldier_placeholder")}
            data-testid="duty-manager-search"
            autoComplete="off"
          />
          {open && filtered.length > 0 && (
            <ul className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto">
              {filtered.map((s) => (
                <li
                  key={s.id}
                  className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                  onMouseDown={(e) => { e.preventDefault(); void handleAdd(s); }}
                  data-testid={`duty-manager-option-${s.id}`}
                >
                  {s.full_name}{" "}
                  <span className="text-gray-400 text-xs">({s.personal_number})</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button
            type="button"
            className="border rounded px-3 py-1 dark:text-gray-100 dark:border-gray-600"
            onClick={onClose}
            data-testid="duty-managers-done"
          >
            {t("app.close")}
          </button>
        </div>
      </div>
      <MessageDialog open={message !== null} title={t("common.error", "שגיאה")} message={message ?? ""} onClose={() => setMessage(null)} />
    </div>
  );
}
