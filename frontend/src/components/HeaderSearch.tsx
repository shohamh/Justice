import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Search } from "lucide-react";
import Fuse from "fuse.js";
import { useAuth } from "../auth/AuthContext";
import { usePublicSettings } from "../hooks/usePublicSettings";
import {
  getPageEntries,
  getQuickActionEntries,
  getHelpTopicEntries,
  type PageEntry,
  type QuickActionEntry,
  type HelpTopicEntry,
} from "../searchRegistry";

export default function HeaderSearch() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const settings = usePublicSettings();
  const gimelimEnabled = settings?.["gimalim.enabled"] !== false;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const accessiblePages = useMemo(
    () => getPageEntries().filter((e) => e.canAccess(user)),
    [user],
  );
  const accessibleActions = useMemo(
    () => getQuickActionEntries().filter((e) => e.canAccess(user)),
    [user],
  );
  const accessibleHelp = useMemo(
    () => getHelpTopicEntries(gimelimEnabled).filter((e) => e.canAccess(user)),
    [user, gimelimEnabled],
  );

  const pageFuse = useMemo(
    () => new Fuse(accessiblePages, { keys: ["labelKey"], threshold: 0.4 }),
    [accessiblePages],
  );
  const actionFuse = useMemo(
    () => new Fuse(accessibleActions, { keys: ["labelKey"], threshold: 0.4 }),
    [accessibleActions],
  );
  const helpFuse = useMemo(
    () => new Fuse(accessibleHelp, { keys: ["labelKey", "keywords"], threshold: 0.4 }),
    [accessibleHelp],
  );

  const trimmed = query.trim();
  const pageResults: PageEntry[] = trimmed ? pageFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];
  const actionResults: QuickActionEntry[] = trimmed ? actionFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];
  const helpResults: HelpTopicEntry[] = trimmed ? helpFuse.search(trimmed).map((r) => r.item).slice(0, 8) : [];

  const hasAnyResults = pageResults.length > 0 || actionResults.length > 0 || helpResults.length > 0;

  function openPanel() {
    setOpen(true);
  }

  function closePanel() {
    setOpen(false);
    setQuery("");
  }

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        openPanel();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <button
        onClick={openPanel}
        aria-label={t("search.placeholder")}
        className="text-gray-500 hover:text-indigo-600"
      >
        <Search size={22} />
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/30" onClick={closePanel}>
          <div
            className="bg-white dark:bg-gray-800 mx-auto mt-16 max-w-xl rounded-lg shadow-lg p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={inputRef}
              role="combobox"
              aria-expanded={open}
              aria-label={t("search.placeholder")}
              placeholder={t("search.placeholder")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") closePanel();
              }}
              className="w-full border rounded px-3 py-2 bg-transparent dark:text-gray-100"
            />
            {trimmed !== "" && (
              <div className="mt-2 max-h-96 overflow-y-auto">
                {pageResults.length > 0 && (
                  <div>
                    <div className="text-xs text-gray-400 px-1">{t("search.categories.page")}</div>
                    {pageResults.map((r) => (
                      <div key={r.id} role="option" className="px-2 py-1">
                        {t(r.labelKey)}
                      </div>
                    ))}
                  </div>
                )}
                {actionResults.length > 0 && (
                  <div>
                    <div className="text-xs text-gray-400 px-1">{t("search.categories.action")}</div>
                    {actionResults.map((r) => (
                      <div key={r.id} role="option" className="px-2 py-1">
                        {t(r.labelKey)}
                      </div>
                    ))}
                  </div>
                )}
                {helpResults.length > 0 && (
                  <div>
                    <div className="text-xs text-gray-400 px-1">{t("search.categories.help")}</div>
                    {helpResults.map((r) => (
                      <div key={r.id} role="option" className="px-2 py-1">
                        {t(r.labelKey)}
                      </div>
                    ))}
                  </div>
                )}
                {!hasAnyResults && (
                  <div className="text-sm text-gray-500 px-1">{t("search.no_results")}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
